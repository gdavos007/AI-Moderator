"""
FastAPI service for session lifecycle, tokens, and events.
Implements deterministic, observable join flow with agent presence confirmation.
"""
import os
import json
import hashlib
import base64
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
from pathlib import Path
from enum import Enum
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from livekit import api
import uuid

# Load environment variables - try multiple locations
env_paths = [
    Path(__file__).parent.parent.parent / ".env",
    Path.cwd() / ".env",
    Path.home() / "Documents" / "Lever AI" / ".env",
]
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[api] Loaded .env from: {env_path}")
        break

# ============ Configuration ============

LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://ai-moderator-pkxfi93j.livekit.cloud")
GUIDE_FILE = os.getenv("GUIDE_FILE")

# Dev mode flag for extra debug info
DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"

# Redacted URL for logging (hide the project ID partially)
def get_redacted_livekit_url():
    if LIVEKIT_URL:
        # wss://ai-moderator-pkxfi93j.livekit.cloud -> wss://ai-mod*****.livekit.cloud
        parts = LIVEKIT_URL.split(".")
        if len(parts) >= 2:
            host = parts[0]
            if len(host) > 15:
                return host[:15] + "*****." + ".".join(parts[1:])
    return LIVEKIT_URL

REDACTED_LIVEKIT_URL = get_redacted_livekit_url()

# ============ LiveKit API Client ============
# Global LiveKitAPI instance - created on startup when event loop is available
_livekit_api: Optional[api.LiveKitAPI] = None

# Track last error to avoid spamming logs
_last_livekit_error: Optional[str] = None
_last_livekit_error_time: float = 0


def get_livekit_http_url() -> str:
    """Convert WSS URL to HTTPS URL for API calls."""
    return LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")


async def get_livekit_api() -> Optional[api.LiveKitAPI]:
    """Get or create the LiveKitAPI instance."""
    global _livekit_api
    
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        return None
    
    if _livekit_api is None:
        http_url = get_livekit_http_url()
        _livekit_api = api.LiveKitAPI(
            url=http_url,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        )
        print(f"[api][LIVEKIT_INIT] Created LiveKitAPI client url={REDACTED_LIVEKIT_URL}")
    
    return _livekit_api


async def close_livekit_api():
    """Close the LiveKitAPI instance."""
    global _livekit_api
    if _livekit_api is not None:
        await _livekit_api.aclose()
        _livekit_api = None
        print("[api][LIVEKIT_CLOSE] Closed LiveKitAPI client")


# ============ App Lifecycle ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan manager - handles startup and shutdown."""
    # Startup
    print("[api] Starting up...")
    yield
    # Shutdown
    await close_livekit_api()
    print("[api] Shutdown complete")


app = FastAPI(title="LeverAI Focus Group API", version="0.3.0", lifespan=lifespan)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ Models ============

class SessionStatus(str, Enum):
    WAITING = "waiting"
    IN_SESSION = "in_session"
    ENDED = "ended"


class Participant(BaseModel):
    identity: str
    display_name: str
    email: Optional[str] = None
    is_organizer: bool = False
    joined_at: str
    hand_raised: bool = False
    hand_raised_at: Optional[str] = None
    is_speaking: bool = False
    is_agent: bool = False


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    room_name: str = ""
    status: SessionStatus = SessionStatus.WAITING
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    guide_title: Optional[str] = None
    guide_hash: Optional[str] = None
    current_question_id: Optional[str] = None
    current_section_id: Optional[str] = None
    participants: List[Participant] = Field(default_factory=list)
    hand_raise_queue: List[str] = Field(default_factory=list)
    agent_joined: bool = False
    agent_identity: Optional[str] = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.room_name:
            # Deterministic room name: focusgroup-<timestamp>-<shortid>
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            self.room_name = f"focusgroup-{timestamp}-{self.id}"


class JoinRequest(BaseModel):
    displayName: str
    email: Optional[str] = None
    isOrganizer: Optional[bool] = False


class RaiseHandRequest(BaseModel):
    participantId: str


# ============ State ============

sessions: Dict[str, Session] = {}


# ============ Helpers ============

def get_guide_info() -> tuple[str | None, str | None]:
    """Load guide title and compute hash for traceability."""
    if not GUIDE_FILE or not os.path.exists(GUIDE_FILE):
        return None, None
    try:
        with open(GUIDE_FILE, "r") as f:
            guide = json.load(f)
        title = guide.get("meta", {}).get("title")
        content_hash = hashlib.md5(json.dumps(guide, sort_keys=True).encode()).hexdigest()[:8]
        return title, content_hash
    except Exception:
        return None, None


def decode_token_claims(token: str) -> dict:
    """Decode JWT token to extract claims for logging (without verification)."""
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            # Add padding if needed
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
    except Exception:
        pass
    return {}


def generate_token(room_name: str, identity: str, is_organizer: bool) -> str:
    """Generate a LiveKit access token with structured logging."""
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
    
    token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    token.with_identity(identity)
    token.with_name(identity)
    
    grant = api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    token.with_grants(grant)
    token.with_ttl(timedelta(hours=6))
    
    jwt_token = token.to_jwt()
    
    # Structured log: token minting
    claims = decode_token_claims(jwt_token)
    video_claims = claims.get("video", {})
    print(f"[api][TOKEN_MINT] room={room_name} identity={identity} "
          f"token_room_claim={video_claims.get('room', 'MISSING')} "
          f"livekit_url={REDACTED_LIVEKIT_URL} is_organizer={is_organizer}")
    
    return jwt_token


def session_to_response(s: Session) -> dict:
    """Convert session to camelCase response."""
    return {
        "id": s.id,
        "roomName": s.room_name,
        "status": s.status.value,
        "createdAt": s.created_at,
        "startedAt": s.started_at,
        "endedAt": s.ended_at,
        "guideTitle": s.guide_title,
        "currentQuestionId": s.current_question_id,
        "currentSectionId": s.current_section_id,
        "participants": [
            {
                "identity": p.identity,
                "displayName": p.display_name,
                "email": p.email,
                "isOrganizer": p.is_organizer,
                "joinedAt": p.joined_at,
                "handRaised": p.hand_raised,
                "handRaisedAt": p.hand_raised_at,
                "isSpeaking": p.is_speaking,
                "isAgent": p.is_agent,
            }
            for p in s.participants
        ],
        "handRaiseQueue": s.hand_raise_queue,
        "agentJoined": s.agent_joined,
        "agentIdentity": s.agent_identity,
    }


def is_agent_identity(identity: str) -> bool:
    """
    Check if an identity belongs to the agent.
    Agent identity rules (deterministic):
    - Starts with "agent" (case-insensitive)
    - Contains "moderator" (case-insensitive)
    """
    identity_lower = identity.lower()
    return identity_lower.startswith("agent") or "moderator" in identity_lower


# ============ LiveKit Room Service Functions ============

async def list_room_participants(room_name: str) -> tuple[List[dict], Optional[str]]:
    """
    List participants in a LiveKit room.
    
    Returns: (participants_list, error_message)
    - On success: ([{identity, name, state, ...}], None)
    - On failure: ([], error_message)
    """
    global _last_livekit_error, _last_livekit_error_time
    
    lk_api = await get_livekit_api()
    if lk_api is None:
        return [], "LiveKit credentials not configured"
    
    try:
        response = await lk_api.room.list_participants(
            api.ListParticipantsRequest(room=room_name)
        )
        
        participants = [
            {
                "identity": p.identity,
                "name": p.name,
                "state": str(p.state) if hasattr(p, 'state') else "unknown",
                "joined_at": p.joined_at if hasattr(p, 'joined_at') else 0,
                "is_publisher": p.is_publisher if hasattr(p, 'is_publisher') else False,
            }
            for p in response.participants
        ]
        
        identities = [p["identity"] for p in participants]
        print(f"[api][ROOM_PARTICIPANTS] room={room_name} count={len(participants)} identities={identities}")
        
        # Clear error state on success
        _last_livekit_error = None
        
        return participants, None
        
    except Exception as e:
        error_msg = str(e)
        
        # Rate-limit error logging (only log if error changed or >10s since last)
        current_time = asyncio.get_event_loop().time()
        if error_msg != _last_livekit_error or (current_time - _last_livekit_error_time) > 10:
            print(f"[api][ERROR] Failed to list room participants: {error_msg}")
            _last_livekit_error = error_msg
            _last_livekit_error_time = current_time
        
        return [], error_msg


async def list_rooms() -> tuple[List[str], Optional[str]]:
    """
    List all active rooms in LiveKit.
    
    Returns: (room_names_list, error_message)
    """
    lk_api = await get_livekit_api()
    if lk_api is None:
        return [], "LiveKit credentials not configured"
    
    try:
        response = await lk_api.room.list_rooms(api.ListRoomsRequest())
        room_names = [r.name for r in response.rooms]
        return room_names, None
    except Exception as e:
        return [], str(e)


async def check_agent_in_room(room_name: str, max_attempts: int = 10, delay: float = 1.5) -> tuple[bool, Optional[str]]:
    """
    Check if agent has joined the room with retries.
    
    Returns: (agent_found, agent_identity)
    """
    last_error = None
    
    for attempt in range(max_attempts):
        participants, error = await list_room_participants(room_name)
        
        if error:
            last_error = error
            # Only log on first attempt or if error is significant
            if attempt == 0:
                print(f"[api][AGENT_CHECK] room={room_name} attempt={attempt+1}/{max_attempts} error={error}")
        else:
            for p in participants:
                identity = p.get("identity", "")
                if is_agent_identity(identity):
                    print(f"[api][AGENT_FOUND] room={room_name} agent_identity={identity} attempt={attempt+1}")
                    return True, identity
        
        if attempt < max_attempts - 1:
            # Log progress every few attempts
            if attempt % 3 == 0:
                print(f"[api][AGENT_CHECK] room={room_name} attempt={attempt+1}/{max_attempts} agent_found=false")
            await asyncio.sleep(delay)
    
    print(f"[api][AGENT_NOT_FOUND] room={room_name} after {max_attempts} attempts last_error={last_error}")
    return False, None


# ============ Endpoints ============

@app.get("/api/health")
async def health():
    """Basic health check."""
    return {
        "status": "ok",
        "service": "lever-api",
        "version": "0.3.0",
        "livekit_url": REDACTED_LIVEKIT_URL,
        "livekit_configured": bool(LIVEKIT_API_KEY and LIVEKIT_API_SECRET),
    }


@app.get("/api/agent/health")
async def agent_health():
    """
    Check if agent worker is reachable and LiveKit connection works.
    This verifies we can connect to LiveKit RoomService.
    """
    errors = []
    
    # Check LiveKit credentials
    if not LIVEKIT_API_KEY:
        errors.append("LIVEKIT_API_KEY not configured")
    if not LIVEKIT_API_SECRET:
        errors.append("LIVEKIT_API_SECRET not configured")
    
    # Try to list rooms to verify connectivity
    livekit_reachable = False
    active_rooms = []
    
    if not errors:
        rooms, error = await list_rooms()
        if error:
            errors.append(f"LiveKit connection failed: {error}")
        else:
            livekit_reachable = True
            active_rooms = rooms
    
    return {
        "status": "ok" if not errors else "error",
        "livekit_url": REDACTED_LIVEKIT_URL,
        "livekit_reachable": livekit_reachable,
        "active_rooms": active_rooms,
        "errors": errors,
    }


@app.get("/api/session/debug")
async def session_debug(room: str = Query(..., description="Room name to debug")):
    """
    Debug endpoint to list participants in a LiveKit room.
    Useful for diagnosing room mismatch or agent join issues.
    """
    participants, error = await list_room_participants(room)
    
    # Find matching session
    matching_session = None
    for sid, s in sessions.items():
        if s.room_name == room:
            matching_session = session_to_response(s)
            break
    
    agent_present = any(is_agent_identity(p.get("identity", "")) for p in participants)
    agent_identity = None
    for p in participants:
        if is_agent_identity(p.get("identity", "")):
            agent_identity = p.get("identity")
            break
    
    response = {
        "room": room,
        "livekit_url": REDACTED_LIVEKIT_URL,
        "livekit_participants": participants,
        "participant_count": len(participants),
        "agent_present": agent_present,
        "agent_identity": agent_identity,
        "api_session": matching_session,
        "api_session_found": matching_session is not None,
    }
    
    # Add debug info in dev mode
    if DEV_MODE and error:
        response["livekit_error"] = error
    
    return response


@app.post("/api/sessions")
async def create_session():
    """Create a new session with deterministic room name."""
    guide_title, guide_hash = get_guide_info()
    session = Session(guide_title=guide_title, guide_hash=guide_hash)
    sessions[session.id] = session
    
    print(f"[api][SESSION_CREATE] session_id={session.id} room_name={session.room_name} "
          f"guide={guide_title} livekit_url={REDACTED_LIVEKIT_URL}")
    
    return session_to_response(session)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_to_response(sessions[session_id])


@app.post("/api/sessions/{session_id}/join")
async def join_session(session_id: str, request: JoinRequest):
    """Join a session and get a LiveKit token."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if session.status == SessionStatus.ENDED:
        raise HTTPException(status_code=400, detail="Session has ended")
    
    # Generate deterministic identity
    identity = f"{request.displayName.replace(' ', '_').lower()}_{len(session.participants) + 1}"
    is_organizer = request.isOrganizer or False
    
    participant = Participant(
        identity=identity,
        display_name=request.displayName,
        email=request.email,
        is_organizer=is_organizer,
        joined_at=datetime.now(timezone.utc).isoformat(),
    )
    session.participants.append(participant)
    
    # Generate token with structured logging
    token = generate_token(session.room_name, identity, is_organizer)
    
    print(f"[api][PARTICIPANT_JOIN] session_id={session_id} room_name={session.room_name} "
          f"identity={identity} is_organizer={is_organizer}")
    
    return {
        "token": token,
        "sessionId": session_id,
        "roomName": session.room_name,
        "identity": identity,
        "isOrganizer": is_organizer,
        "livekitUrl": LIVEKIT_URL,  # Return for frontend logging
    }


@app.post("/api/sessions/{session_id}/start")
async def start_session(session_id: str):
    """
    Start a session. This:
    1. Updates session status
    2. Optionally creates the room in LiveKit
    3. Waits for agent to join (with timeout)
    4. Returns success only when agent is confirmed present
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if session.status != SessionStatus.WAITING:
        raise HTTPException(status_code=400, detail="Session already started or ended")
    
    print(f"[api][SESSION_START_BEGIN] session_id={session_id} room_name={session.room_name}")
    
    # Update status
    session.status = SessionStatus.IN_SESSION
    session.started_at = datetime.now(timezone.utc).isoformat()
    
    # Wait for agent to join (the agent should auto-dispatch when room has participants)
    # Give it up to 15 seconds with 1.5 second intervals
    agent_found, agent_identity = await check_agent_in_room(session.room_name, max_attempts=10, delay=1.5)
    
    if agent_found:
        session.agent_joined = True
        session.agent_identity = agent_identity
        
        print(f"[api][SESSION_START_SUCCESS] session_id={session_id} room_name={session.room_name} "
              f"agent_identity={session.agent_identity}")
    else:
        print(f"[api][SESSION_START_WARNING] session_id={session_id} room_name={session.room_name} "
              f"agent_not_joined=true - session started without agent confirmation")
    
    return {
        **session_to_response(session),
        "agentConfirmed": agent_found,
        "message": "Session started" + ("" if agent_found else " (warning: agent not confirmed)")
    }


@app.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """
    Get session status including real-time agent presence check.
    This endpoint never 500s due to LiveKit issues - it gracefully degrades.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    # Check current room participants (with error handling)
    participants, livekit_error = await list_room_participants(session.room_name)
    
    agent_present = False
    agent_identity = session.agent_identity
    
    if not livekit_error:
        for p in participants:
            identity = p.get("identity", "")
            if is_agent_identity(identity):
                agent_present = True
                agent_identity = identity
                break
        
        # Update session state if agent newly detected
        if agent_present and not session.agent_joined:
            session.agent_joined = True
            session.agent_identity = agent_identity
    
    response = {
        "sessionId": session_id,
        "roomName": session.room_name,
        "status": session.status.value,
        "agentJoined": agent_present if not livekit_error else session.agent_joined,
        "agentIdentity": agent_identity,
        "participantCount": len(participants),
        "livekitParticipants": [p.get("identity") for p in participants],
    }
    
    # Add debug info in dev mode
    if DEV_MODE and livekit_error:
        response["livekit_error"] = livekit_error
    
    return response


@app.post("/api/sessions/{session_id}/end")
async def end_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if session.status == SessionStatus.ENDED:
        raise HTTPException(status_code=400, detail="Session already ended")
    
    session.status = SessionStatus.ENDED
    session.ended_at = datetime.now(timezone.utc).isoformat()
    
    print(f"[api][SESSION_END] session_id={session_id} room_name={session.room_name}")
    
    return session_to_response(session)


@app.post("/api/sessions/{session_id}/raise-hand")
async def raise_hand(session_id: str, request: RaiseHandRequest):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    participant = next(
        (p for p in session.participants if p.identity == request.participantId),
        None,
    )
    
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    
    if not participant.hand_raised:
        participant.hand_raised = True
        participant.hand_raised_at = datetime.now(timezone.utc).isoformat()
        
        if participant.identity not in session.hand_raise_queue:
            session.hand_raise_queue.append(participant.identity)
        
        print(f"[api][HAND_RAISE] session_id={session_id} participant={participant.identity}")
    
    return {
        "success": True,
        "queuePosition": session.hand_raise_queue.index(participant.identity),
    }


@app.post("/api/sessions/{session_id}/lower-hand")
async def lower_hand(session_id: str, request: RaiseHandRequest):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    participant = next(
        (p for p in session.participants if p.identity == request.participantId),
        None,
    )
    
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    
    participant.hand_raised = False
    participant.hand_raised_at = None
    
    if participant.identity in session.hand_raise_queue:
        session.hand_raise_queue.remove(participant.identity)
    
    print(f"[api][HAND_LOWER] session_id={session_id} participant={participant.identity}")
    
    return {"success": True}


if __name__ == "__main__":
    import uvicorn
    print(f"[api] Starting server...")
    print(f"[api] LiveKit URL: {REDACTED_LIVEKIT_URL}")
    print(f"[api] Guide file: {GUIDE_FILE}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
