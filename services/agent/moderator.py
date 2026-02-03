"""
LiveKit Voice Agent – Focus Group Moderator (Enhanced MVP)
Event-driven speech detection with cancellable timers, turn timing,
silence prompting, and wrap-up management.

Run with: python moderator.py dev
"""

from dotenv import load_dotenv
import asyncio
import aiohttp
import json
import os
import re
import time
import uuid
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import openai, deepgram, silero

# Load ENV from project root
env_paths = [
    Path(__file__).parent.parent.parent / ".env",
    Path.cwd() / ".env",
    Path.home() / "Documents" / "Lever AI" / ".env",
]
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"[moderator] Loaded .env from: {env_path}")
        break

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://ai-moderator-pkxfi93j.livekit.cloud")

def get_redacted_livekit_url():
    if LIVEKIT_URL:
        parts = LIVEKIT_URL.split(".")
        if len(parts) >= 2 and len(parts[0]) > 15:
            return parts[0][:15] + "*****." + ".".join(parts[1:])
    return LIVEKIT_URL

REDACTED_LIVEKIT_URL = get_redacted_livekit_url()

# ============ Timing Configuration ============
# Feature flag for new turn timers
TURN_TIMERS_ENABLED = os.getenv("TURN_TIMERS_ENABLED", "true").lower() == "true"

# Silence handling
SILENCE_PROMPT_SECONDS = float(os.getenv("SILENCE_PROMPT_SECONDS", "12"))
SILENCE_GRACE_SECONDS = float(os.getenv("SILENCE_GRACE_SECONDS", "8"))

# Long-answer handling
MAX_ANSWER_SECONDS = float(os.getenv("MAX_ANSWER_SECONDS", "45"))
WRAPUP_SECONDS = float(os.getenv("WRAPUP_SECONDS", "15"))

# End of speech detection
END_OF_SPEECH_SILENCE = 4.0  # Seconds of silence after speech to consider "done"

# Legacy (kept for backward compat when TURN_TIMERS_ENABLED=false)
SILENCE_TIMEOUT = 20.0
MAX_RESPONSE_TIME = 60.0

# ============ Agent Speech Lines ============
SPEECH_SILENCE_PROMPT = "{name}, I'd love to hear your thoughts. Anything you'd add?"
SPEECH_SILENCE_MOVEON = "No worries—let's come back if we have time."
SPEECH_WRAPUP_PROMPT = "{name}, we're going to need to wrap it up so we can get to others. Can you spend the next ten to fifteen seconds wrapping up your thoughts?"
SPEECH_WRAPUP_END = "Got it—thank you."

# Patterns to detect "repeat" requests
REPEAT_PATTERNS = [
    r"\brepeat\b", r"\bsay that again\b", r"\bwhat was the question\b",
    r"\bdidn'?t (hear|understand|catch)\b", r"\bcouldn'?t (hear|understand)\b",
    r"\bpardon\b", r"\bcome again\b", r"\bone more time\b",
]


# ============ Structured Logging ============
def log_event(event: str, **kwargs):
    """Structured log with timestamp and correlation ID."""
    ts = int(time.time() * 1000)  # milliseconds
    parts = [f"[{ts}ms][{event}]"]
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    print(" ".join(parts))


# ============ Question State Machine ============
class QuestionState(Enum):
    IDLE = "idle"
    AGENT_SPEAKING = "agent_speaking"
    WAITING_FOR_RESPONSE = "waiting_for_response"
    SILENCE_PROMPTED = "silence_prompted"
    USER_SPEAKING = "user_speaking"
    WRAPUP_REQUESTED = "wrapup_requested"
    RESPONSE_COMPLETE = "response_complete"
    TIMEOUT = "timeout"
    SILENCE_SKIPPED = "silence_skipped"


@dataclass
class QuestionContext:
    """State for a single question turn (legacy, kept for backward compat)."""
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    question_id: str = ""
    question_index: int = 0
    state: QuestionState = QuestionState.IDLE
    
    # Timing
    question_asked_at: float = 0
    timer_started_at: float = 0
    timer_duration: float = 0
    
    # Transcript collection
    transcripts: List[str] = field(default_factory=list)
    first_speech_at: float = 0
    last_speech_at: float = 0
    has_speech: bool = False
    
    # Timer handle (for cancellation)
    timeout_task: Optional[asyncio.Task] = None
    
    def add_transcript(self, text: str):
        """Add a transcript segment with structured logging."""
        now = time.time()
        if not self.has_speech:
            self.first_speech_at = now
            self.has_speech = True
            log_event("USER_SPEECH_START", 
                      cid=self.correlation_id, 
                      qid=self.question_id,
                      elapsed_ms=int((now - self.question_asked_at) * 1000))
        
        self.last_speech_at = now
        self.transcripts.append(text)
        
        log_event("TRANSCRIPT_RECEIVED",
                  cid=self.correlation_id,
                  qid=self.question_id,
                  text=text[:50] + ("..." if len(text) > 50 else ""),
                  transcript_count=len(self.transcripts))
    
    def get_full_text(self) -> str:
        return " ".join(self.transcripts)
    
    def time_since_last_speech(self) -> float:
        if self.last_speech_at == 0:
            return float('inf')
        return time.time() - self.last_speech_at
    
    def is_asking_to_repeat(self) -> bool:
        text = self.get_full_text().lower()
        for pattern in REPEAT_PATTERNS:
            if re.search(pattern, text):
                return True
        return False
    
    def cancel_timer(self):
        """Cancel the timeout timer if running."""
        if self.timeout_task and not self.timeout_task.done():
            self.timeout_task.cancel()
            log_event("TIMER_CANCELLED",
                      cid=self.correlation_id,
                      qid=self.question_id,
                      reason="speech_detected" if self.has_speech else "manual")
            self.timeout_task = None
    
    def reset(self):
        """Reset for next question."""
        self.cancel_timer()
        self.transcripts = []
        self.first_speech_at = 0
        self.last_speech_at = 0
        self.has_speech = False
        self.state = QuestionState.IDLE


@dataclass
class TurnController:
    """
    Manages per-participant turn timers with turn_id guards.
    Prevents ghost timers from firing on subsequent participants.
    """
    turn_id: int = 0
    participant_id: str = ""
    participant_name: str = ""
    question_text: str = ""
    question_id: str = ""
    
    # Timer tasks (all must check turn_id before firing)
    silence_prompt_task: Optional[asyncio.Task] = None
    silence_grace_task: Optional[asyncio.Task] = None
    max_answer_task: Optional[asyncio.Task] = None
    wrapup_task: Optional[asyncio.Task] = None
    end_of_speech_task: Optional[asyncio.Task] = None
    
    # Events for coordination
    turn_ended: asyncio.Event = field(default_factory=asyncio.Event)
    speech_detected: asyncio.Event = field(default_factory=asyncio.Event)
    
    # Timing state
    turn_started_at: float = 0
    first_speech_at: float = 0
    last_speech_at: float = 0
    has_speech: bool = False
    silence_prompted: bool = False
    wrapup_prompted: bool = False
    
    # Transcript buffer for this turn
    transcripts: List[str] = field(default_factory=list)
    
    def start_turn(self, participant_id: str, participant_name: str, question_text: str, question_id: str = ""):
        """Initialize a new turn, incrementing turn_id to invalidate stale tasks."""
        self.cancel_all_tasks()
        self.turn_id += 1
        self.participant_id = participant_id
        self.participant_name = participant_name
        self.question_text = question_text
        self.question_id = question_id
        self.turn_started_at = time.time()
        self.first_speech_at = 0
        self.last_speech_at = 0
        self.has_speech = False
        self.silence_prompted = False
        self.wrapup_prompted = False
        self.transcripts = []
        self.turn_ended = asyncio.Event()
        self.speech_detected = asyncio.Event()
        
        log_event("TURN_START",
                  turn_id=self.turn_id,
                  participant=participant_name,
                  qid=question_id)
    
    def on_speech_detected(self, transcript: str = ""):
        """Called when transcript is received for current participant."""
        now = time.time()
        if not self.has_speech:
            self.first_speech_at = now
            self.has_speech = True
            log_event("TURN_SPEECH_START",
                      turn_id=self.turn_id,
                      participant=self.participant_name,
                      elapsed_ms=int((now - self.turn_started_at) * 1000))
        
        self.last_speech_at = now
        self.speech_detected.set()
        
        if transcript:
            self.transcripts.append(transcript)
        
        # Cancel silence timers (but not max answer / wrapup)
        self._cancel_task("silence_prompt", self.silence_prompt_task)
        self._cancel_task("silence_grace", self.silence_grace_task)
        self.silence_prompt_task = None
        self.silence_grace_task = None
    
    def on_turn_end(self, reason: str):
        """End the current turn and cancel all tasks."""
        log_event("TURN_END",
                  turn_id=self.turn_id,
                  participant=self.participant_name,
                  reason=reason,
                  has_speech=self.has_speech)
        self.turn_ended.set()
        self.cancel_all_tasks()
    
    def cancel_all_tasks(self):
        """Cancel all timer tasks."""
        for name, task in [
            ("silence_prompt", self.silence_prompt_task),
            ("silence_grace", self.silence_grace_task),
            ("max_answer", self.max_answer_task),
            ("wrapup", self.wrapup_task),
            ("end_of_speech", self.end_of_speech_task),
        ]:
            self._cancel_task(name, task)
        self.silence_prompt_task = None
        self.silence_grace_task = None
        self.max_answer_task = None
        self.wrapup_task = None
        self.end_of_speech_task = None
    
    def _cancel_task(self, name: str, task: Optional[asyncio.Task]):
        if task and not task.done():
            task.cancel()
            log_event("TIMER_CANCELLED", turn_id=self.turn_id, timer=name)
    
    def time_since_last_speech(self) -> float:
        if self.last_speech_at == 0:
            return float('inf')
        return time.time() - self.last_speech_at
    
    def answer_duration(self) -> float:
        if self.first_speech_at == 0:
            return 0
        return time.time() - self.first_speech_at
    
    def get_full_text(self) -> str:
        return " ".join(self.transcripts)
    
    def is_asking_to_repeat(self) -> bool:
        text = self.get_full_text().lower()
        for pattern in REPEAT_PATTERNS:
            if re.search(pattern, text):
                return True
        return False


class ModeratorState:
    """State management for the moderator agent."""
    
    def __init__(self):
        self.guide: Optional[Dict] = None
        self.session_id: Optional[str] = None
        self.room_name: Optional[str] = None
        self.section_idx: int = 0
        self.question_idx: int = 0
        self.section_script_read: bool = False
        self.participants: Dict[str, Dict] = {}
        self.session_started: bool = False
        self.session_ended: bool = False
        self.current_question: QuestionContext = QuestionContext()
        self.agent_speaking: bool = False
        self.turn_controller: TurnController = TurnController()
        # Background polling task reference
        self._status_poller_task: Optional[asyncio.Task] = None
        # Agent session reference for cancellation
        self._agent_session: Optional[AgentSession] = None
    
    def trigger_shutdown(self, reason: str = "session_ended"):
        """Immediately trigger shutdown: cancel all timers and mark session ended."""
        log_event("SHUTDOWN_TRIGGERED", reason=reason, session_id=self.session_id)
        self.session_ended = True
        # Cancel all turn timers
        self.turn_controller.cancel_all_tasks()
        # Cancel question timer
        self.current_question.cancel_timer()
        # Cancel poller
        if self._status_poller_task and not self._status_poller_task.done():
            self._status_poller_task.cancel()
    
    async def start_status_poller(self):
        """Start background task that polls session status and triggers shutdown when ended."""
        if not self.session_id:
            return
        self._status_poller_task = asyncio.create_task(self._poll_session_status())
    
    async def _poll_session_status(self):
        """Background poller that checks session status every 2 seconds."""
        log_event("STATUS_POLLER_START", session_id=self.session_id)
        try:
            async with aiohttp.ClientSession() as http:
                while not self.session_ended:
                    try:
                        async with http.get(f"{API_BASE}/api/sessions/{self.session_id}") as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get("status") == "ended":
                                    log_event("STATUS_POLL_ENDED_DETECTED", session_id=self.session_id)
                                    self.trigger_shutdown("status_poll_ended")
                                    return
                            elif resp.status == 404:
                                log_event("STATUS_POLL_SESSION_GONE", session_id=self.session_id)
                                self.trigger_shutdown("session_not_found")
                                return
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        log_event("STATUS_POLL_ERROR", error=str(e)[:50])
                    
                    await asyncio.sleep(2)
        except asyncio.CancelledError:
            log_event("STATUS_POLLER_CANCELLED")
        finally:
            log_event("STATUS_POLLER_EXIT")
    
    def load_guide(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            self.guide = json.load(f)
        return True
    
    def get_current(self) -> tuple[Optional[Dict], Optional[Dict]]:
        if not self.guide:
            return None, None
        sections = self.guide.get("sections", [])
        if self.section_idx >= len(sections):
            return None, None
        section = sections[self.section_idx]
        questions = section.get("questions", [])
        question = questions[self.question_idx] if self.question_idx < len(questions) else None
        return section, question
    
    def advance(self):
        if not self.guide:
            return
        sections = self.guide.get("sections", [])
        if self.section_idx >= len(sections):
            return
        section = sections[self.section_idx]
        questions = section.get("questions", [])
        
        if self.question_idx + 1 < len(questions):
            self.question_idx += 1
            self.section_script_read = True
        else:
            self.section_idx += 1
            self.question_idx = 0
            self.section_script_read = False
    
    def is_complete(self) -> bool:
        if not self.guide:
            return True
        return self.section_idx >= len(self.guide.get("sections", []))
    
    def get_all_participants(self) -> List[Dict]:
        return list(self.participants.values())


class FocusGroupModerator(Agent):
    def __init__(self):
        super().__init__(
            instructions="""You are a professional focus group moderator named Justin.
            Be neutral, friendly, and professional. Keep discussions on track.
            If a participant asks you to repeat the question, please do so.""",
            tools=[]
        )


# ============ Turn Timing: Event-Driven Wait with Silence + Wrap-up ============

async def wait_for_turn_completion(
    state: ModeratorState,
    session: AgentSession,
    question_id: str,
    question_index: int,
    participant_name: str,
) -> tuple[bool, bool, str]:
    """
    Event-driven turn management with silence prompting and wrap-up.
    
    Returns: (got_response, asked_to_repeat, end_reason)
    end_reason: "answer" | "silence_skip" | "wrapup" | "repeat"
    """
    tc = state.turn_controller
    
    # Events for different outcomes
    silence_skip_event = asyncio.Event()
    answer_complete_event = asyncio.Event()
    wrapup_complete_event = asyncio.Event()
    
    # Capture turn_id at start to guard against ghost timers
    current_turn_id = tc.turn_id
    
    def is_current_turn() -> bool:
        return tc.turn_id == current_turn_id and not tc.turn_ended.is_set()
    
    async def silence_prompt_watcher():
        """Wait for silence prompt threshold, then prompt user."""
        try:
            await asyncio.sleep(SILENCE_PROMPT_SECONDS)
            if not is_current_turn():
                return
            if tc.has_speech:
                return  # Already speaking, no need to prompt
            
            log_event("SILENCE_PROMPT_TRIGGERED",
                      turn_id=current_turn_id,
                      elapsed_s=round(time.time() - tc.turn_started_at, 1))
            
            tc.silence_prompted = True
            
            # Say the prompt
            try:
                state.agent_speaking = True
                await session.say(SPEECH_SILENCE_PROMPT.format(name=participant_name))
            except RuntimeError:
                pass
            finally:
                state.agent_speaking = False
            
            # Start grace timer
            if is_current_turn():
                tc.silence_grace_task = asyncio.create_task(silence_grace_watcher())
            
        except asyncio.CancelledError:
            pass
    
    async def silence_grace_watcher():
        """Wait for grace period after prompt, then skip participant."""
        try:
            await asyncio.sleep(SILENCE_GRACE_SECONDS)
            if not is_current_turn():
                return
            if tc.has_speech:
                return  # Started speaking during grace
            
            log_event("SILENCE_SKIP_TRIGGERED",
                      turn_id=current_turn_id,
                      elapsed_s=round(time.time() - tc.turn_started_at, 1))
            
            silence_skip_event.set()
            
        except asyncio.CancelledError:
            pass
    
    async def max_answer_watcher():
        """Watch for max answer duration and trigger wrap-up."""
        try:
            # Wait until speech starts, then track duration
            await tc.speech_detected.wait()
            if not is_current_turn():
                return
            
            # Now wait for max answer duration from first speech
            remaining = MAX_ANSWER_SECONDS - tc.answer_duration()
            if remaining > 0:
                await asyncio.sleep(remaining)
            
            if not is_current_turn():
                return
            
            log_event("WRAPUP_TRIGGERED",
                      turn_id=current_turn_id,
                      answer_duration_s=round(tc.answer_duration(), 1))
            
            tc.wrapup_prompted = True
            
            # Say the wrap-up prompt
            try:
                state.agent_speaking = True
                await session.say(SPEECH_WRAPUP_PROMPT)
            except RuntimeError:
                pass
            finally:
                state.agent_speaking = False
            
            # Start wrapup timer
            if is_current_turn():
                tc.wrapup_task = asyncio.create_task(wrapup_end_watcher())
            
        except asyncio.CancelledError:
            pass
    
    async def wrapup_end_watcher():
        """End turn after wrap-up period expires."""
        try:
            await asyncio.sleep(WRAPUP_SECONDS)
            if not is_current_turn():
                return
            
            log_event("WRAPUP_END_TRIGGERED", turn_id=current_turn_id)
            wrapup_complete_event.set()
            
        except asyncio.CancelledError:
            pass
    
    async def end_of_speech_watcher():
        """Watch for end of speech (silence after speaking)."""
        try:
            while is_current_turn():
                await asyncio.sleep(0.5)
                
                if tc.has_speech:
                    silence_duration = tc.time_since_last_speech()
                    
                    # Check if user finished speaking (enough silence)
                    if silence_duration >= END_OF_SPEECH_SILENCE:
                        log_event("END_OF_SPEECH_DETECTED",
                                  turn_id=current_turn_id,
                                  silence_s=round(silence_duration, 2),
                                  transcript_count=len(tc.transcripts))
                        answer_complete_event.set()
                        return
                
        except asyncio.CancelledError:
            pass
    
    # Session end watcher
    session_ended_event = asyncio.Event()
    
    async def session_end_watcher():
        """Watch for session ending."""
        try:
            while not state.session_ended:
                await asyncio.sleep(0.25)
            session_ended_event.set()
        except asyncio.CancelledError:
            pass
    
    # Start watchers
    tc.silence_prompt_task = asyncio.create_task(silence_prompt_watcher())
    tc.max_answer_task = asyncio.create_task(max_answer_watcher())
    tc.end_of_speech_task = asyncio.create_task(end_of_speech_watcher())
    session_end_task = asyncio.create_task(session_end_watcher())
    
    log_event("TURN_WAIT_STARTED",
              turn_id=current_turn_id,
              participant=participant_name,
              silence_prompt_s=SILENCE_PROMPT_SECONDS,
              max_answer_s=MAX_ANSWER_SECONDS)
    
    try:
        # Wait for any terminal event (including session end)
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(silence_skip_event.wait()),
                asyncio.create_task(answer_complete_event.wait()),
                asyncio.create_task(wrapup_complete_event.wait()),
                asyncio.create_task(tc.turn_ended.wait()),
                asyncio.create_task(session_ended_event.wait()),
            ],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel pending wait tasks
        for task in pending:
            task.cancel()
    
    finally:
        # Cleanup all timer tasks
        tc.cancel_all_tasks()
        session_end_task.cancel()
    
    # Check for session end first
    if session_ended_event.is_set() or state.session_ended:
        log_event("TURN_ABORTED_SESSION_ENDED", turn_id=current_turn_id)
        return False, False, "session_ended"
    
    # Determine outcome
    if silence_skip_event.is_set():
        return False, False, "silence_skip"
    
    if wrapup_complete_event.is_set():
        # Check if asking to repeat (unlikely after wrapup, but check)
        if tc.is_asking_to_repeat():
            return True, True, "repeat"
        return True, False, "wrapup"
    
    if answer_complete_event.is_set():
        # Check if asking to repeat
        if tc.is_asking_to_repeat():
            return True, True, "repeat"
        return True, False, "answer"
    
    # Turn was ended externally (session end, disconnect, etc.)
    return tc.has_speech, False, "external"


# ============ Legacy Wait Function (for backward compat) ============

async def wait_for_response_event_driven(
    state: ModeratorState,
    question_id: str,
    question_index: int,
) -> tuple[bool, bool]:
    """
    Legacy event-driven waiting for participant response.
    Used when TURN_TIMERS_ENABLED=false.
    
    Returns: (got_response, asked_to_repeat)
    """
    ctx = state.current_question
    ctx.reset()
    ctx.question_id = question_id
    ctx.question_index = question_index
    ctx.correlation_id = str(uuid.uuid4())[:8]
    ctx.state = QuestionState.WAITING_FOR_RESPONSE
    ctx.timer_started_at = time.time()
    ctx.timer_duration = SILENCE_TIMEOUT
    
    log_event("TIMER_STARTED",
              cid=ctx.correlation_id,
              qid=question_id,
              duration_s=SILENCE_TIMEOUT,
              state=ctx.state.value)
    
    timeout_event = asyncio.Event()
    response_complete_event = asyncio.Event()
    
    async def timeout_watcher():
        try:
            await asyncio.sleep(SILENCE_TIMEOUT)
            if not ctx.has_speech:
                log_event("TIMEOUT_FIRED",
                          cid=ctx.correlation_id,
                          qid=question_id,
                          state=ctx.state.value,
                          has_speech=ctx.has_speech,
                          reason="no_speech_detected")
                ctx.state = QuestionState.TIMEOUT
                timeout_event.set()
        except asyncio.CancelledError:
            pass
    
    async def end_of_speech_watcher():
        while True:
            await asyncio.sleep(0.5)
            
            if ctx.has_speech:
                silence_duration = ctx.time_since_last_speech()
                
                if silence_duration >= END_OF_SPEECH_SILENCE:
                    log_event("END_OF_SPEECH_DETECTED",
                              cid=ctx.correlation_id,
                              qid=question_id,
                              silence_s=round(silence_duration, 2),
                              transcript_count=len(ctx.transcripts))
                    ctx.state = QuestionState.RESPONSE_COMPLETE
                    response_complete_event.set()
                    return
            
            if time.time() - ctx.timer_started_at > MAX_RESPONSE_TIME:
                log_event("MAX_TIME_REACHED",
                          cid=ctx.correlation_id,
                          qid=question_id,
                          max_time_s=MAX_RESPONSE_TIME)
                response_complete_event.set()
                return
    
    ctx.timeout_task = asyncio.create_task(timeout_watcher())
    speech_watcher_task = asyncio.create_task(end_of_speech_watcher())
    
    try:
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(timeout_event.wait()),
                asyncio.create_task(response_complete_event.wait()),
            ],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
    
    finally:
        ctx.cancel_timer()
        speech_watcher_task.cancel()
        try:
            await speech_watcher_task
        except asyncio.CancelledError:
            pass
    
    if ctx.state == QuestionState.TIMEOUT:
        log_event("QUESTION_ADVANCED",
                  cid=ctx.correlation_id,
                  qid=question_id,
                  reason="timeout",
                  has_speech=False)
        return False, False
    
    if ctx.is_asking_to_repeat():
        log_event("REPEAT_REQUESTED",
                  cid=ctx.correlation_id,
                  qid=question_id,
                  transcript=ctx.get_full_text()[:100])
        return True, True
    
    log_event("QUESTION_ADVANCED",
              cid=ctx.correlation_id,
              qid=question_id,
              reason="answer_received",
              has_speech=True,
              transcript_preview=ctx.get_full_text()[:50])
    return True, False


# ============ Session Management ============

async def wait_for_session_start(state: ModeratorState, session: AgentSession, room: rtc.Room) -> bool:
    """Wait for the organizer to start the session."""
    log_event("WAITING_FOR_START", session_id=state.session_id)
    await session.say("Welcome everyone! I'm your AI moderator for today's focus group. We're waiting for the organizer to start the session. Please stand by.")
    
    def update_participants():
        for participant in room.remote_participants.values():
            if participant.identity not in state.participants:
                state.participants[participant.identity] = {
                    "identity": participant.identity,
                    "displayName": participant.name or participant.identity,
                    "isOrganizer": "organizer" in participant.identity.lower(),
                }
                log_event("PARTICIPANT_JOINED", identity=participant.identity)
    
    update_participants()
    
    async with aiohttp.ClientSession() as http:
        while not state.session_started and not state.session_ended:
            try:
                async with http.get(f"{API_BASE}/api/sessions/{state.session_id}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "in_session":
                            state.session_started = True
                            log_event("SESSION_STARTED", session_id=state.session_id)
                            for p in data.get("participants", []):
                                state.participants[p["identity"]] = p
                            return True
                        elif data.get("status") == "ended":
                            state.session_ended = True
                            return False
            except Exception as e:
                log_event("SESSION_POLL_ERROR", error=str(e))
            
            update_participants()
            await asyncio.sleep(2)
    
    return False


async def ask_participant(
    state: ModeratorState,
    session: AgentSession,
    participant: Dict,
    question_text: str,
    question_id: str,
    question_index: int,
    is_first: bool = False,
    room: Optional[rtc.Room] = None
) -> bool:
    """Ask a participant and wait for response using turn timing."""
    # Early exit if session ended
    if state.session_ended:
        return False
    
    display_name = participant.get("displayName", participant.get("identity", "Participant"))
    participant_id = participant.get("identity", display_name)
    
    # Switch audio input to the current participant.
    # The LiveKit Agents SDK only listens to ONE participant at a time by default.
    # The LiveKit Agents SDK only listens to ONE participant at a time by default.
    # We must explicitly switch to the current speaker before their turn.
    try:
        session.room_io.set_participant(participant_id)
        log_event("AUDIO_INPUT_SWITCHED", participant=participant_id)
    except Exception as e:
        log_event("AUDIO_INPUT_SWITCH_FAILED", participant=participant_id, error=str(e)[:50])
    
    # Build prompt
    if is_first:
        prompt = f"Let's start with you, {display_name}. Please take your time to share your thoughts."
    else:
        prompt = f"Thank you for sharing. {display_name}, I'd like to hear from you now."
    
    # Mark agent as speaking
    state.agent_speaking = True
    state.current_question.state = QuestionState.AGENT_SPEAKING
    state.current_question.question_asked_at = time.time()
    
    log_event("QUESTION_ASKED",
              qid=question_id,
              index=question_index,
              participant=display_name)
    
    try:
        await session.say(prompt)
    except RuntimeError as e:
        if "closing" in str(e).lower():
            return False
        raise
    finally:
        state.agent_speaking = False
    
    # Check for session end after speaking
    if state.session_ended:
        log_event("ASK_ABORTED", reason="session_ended")
        return False
    
    # Small pause after agent finishes speaking
    await asyncio.sleep(0.5)
    
    log_event("AGENT_DONE_SPEAKING", qid=question_id, participant=display_name)
    
    # Start the turn (initializes TurnController)
    state.turn_controller.start_turn(participant_id, display_name, question_text, question_id)
    state.current_question.state = QuestionState.WAITING_FOR_RESPONSE
    
    max_repeats = 2
    repeat_count = 0
    
    while repeat_count <= max_repeats:
        if TURN_TIMERS_ENABLED:
            got_response, asked_to_repeat, end_reason = await wait_for_turn_completion(
                state, session, question_id, question_index, display_name
            )
        else:
            got_response, asked_to_repeat = await wait_for_response_event_driven(
                state, question_id, question_index
            )
            end_reason = "answer" if got_response else "timeout"
        
        # End the turn
        state.turn_controller.on_turn_end(end_reason)
        
        if asked_to_repeat:
            repeat_count += 1
            if repeat_count <= max_repeats:
                try:
                    state.agent_speaking = True
                    await session.say(f"Of course. Let me repeat that. {question_text}")
                finally:
                    state.agent_speaking = False
                await asyncio.sleep(0.5)
                # Restart turn for repeat
                state.turn_controller.start_turn(participant_id, display_name, question_text, question_id)
                state.current_question.state = QuestionState.WAITING_FOR_RESPONSE
                continue
            else:
                try:
                    await session.say("I've repeated that a couple of times. Let me move on.")
                except RuntimeError:
                    return False
                return True
        
        if not got_response:
            # Silence skip - use the configured speech line
            try:
                await session.say(SPEECH_SILENCE_MOVEON)
            except RuntimeError:
                return False
            return True
        
        if end_reason == "wrapup":
            # Wrap-up completed - use the configured speech line
            try:
                await session.say(SPEECH_WRAPUP_END)
            except RuntimeError:
                return False
            return True
        
        # Normal answer completion
        return True
    
    return True


async def run_discussion(state: ModeratorState, session: AgentSession, room: rtc.Room):
    """Run through the discussion guide."""
    if not state.guide:
        await session.say("I don't have a discussion guide loaded.")
        return
    
    # Helper to check for early exit
    def should_exit():
        return state.session_ended
    
    guide_title = state.guide.get("meta", {}).get("title", "Focus Group")
    log_event("DISCUSSION_START", title=guide_title, turn_timers_enabled=TURN_TIMERS_ENABLED)
    
    participant_names = [p.get("displayName", p.get("identity", "Participant")) 
                         for p in state.participants.values()]
    
    try:
        if participant_names:
            names_str = ", ".join(participant_names)
            await session.say(f"Wonderful! Let's begin our discussion on {guide_title}. I see we have {names_str} with us today. If you need me to repeat a question, just ask.")
        else:
            await session.say(f"Let's begin our discussion on {guide_title}.")
    except RuntimeError:
        return
    
    if should_exit():
        log_event("DISCUSSION_ABORTED", reason="session_ended_early")
        return
    
    await asyncio.sleep(2)
    question_global_index = 0
    
    while not state.is_complete() and not should_exit():
        section, question = state.get_current()
        
        if not section:
            break
        
        # Check for session end before each major step
        if should_exit():
            break
        
        section_script = section.get("script_md", "")
        
        # Read section intro
        if state.question_idx == 0 and section_script and not state.section_script_read:
            log_event("SECTION_START", title=section.get('title', ''))
            try:
                await session.say(section_script)
            except RuntimeError:
                return
            if should_exit():
                break
            state.section_script_read = True
            await asyncio.sleep(2)
        
        if not question:
            state.advance()
            continue
        
        question_id = question.get("id", f"q{question_global_index}")
        question_type = question.get("type", "question")
        question_text = question.get("text", "")
        question_script = question.get("script_md", "")
        
        log_event("QUESTION_BEGIN",
                  qid=question_id,
                  type=question_type,
                  index=question_global_index)
        
        try:
            if question_type == "info":
                if question_script:
                    await session.say(question_script)
                await asyncio.sleep(2)
            
            elif question_type == "closing":
                if question_script:
                    await session.say(question_script)
                await asyncio.sleep(2)
            
            elif question_type == "rollcall":
                await session.say(question_text)
                await asyncio.sleep(1)
                
                for identity, participant in state.participants.items():
                    display_name = participant.get("displayName", identity)
                    
                    # Switch audio input to current participant for rollcall
                    try:
                        session.room_io.set_participant(identity)
                        log_event("AUDIO_INPUT_SWITCHED", participant=identity, context="rollcall")
                    except Exception as e:
                        log_event("AUDIO_INPUT_SWITCH_FAILED", participant=identity, error=str(e)[:50])
                    
                    await session.say(f"{display_name}, please say yes to confirm your consent.")
                    
                    # For rollcall, use simpler timing
                    state.turn_controller.start_turn(identity, display_name, "consent", f"{question_id}_{identity}")
                    state.current_question.state = QuestionState.WAITING_FOR_RESPONSE
                    
                    if TURN_TIMERS_ENABLED:
                        got_response, _, end_reason = await wait_for_turn_completion(
                            state, session, f"{question_id}_{identity}", question_global_index, display_name
                        )
                    else:
                        got_response, _ = await wait_for_response_event_driven(
                            state, f"{question_id}_{identity}", question_global_index
                        )
                        end_reason = "answer" if got_response else "timeout"
                    
                    state.turn_controller.on_turn_end(end_reason)
                    
                    if not got_response:
                        await session.say(f"I didn't hear from {display_name}. We'll follow up separately.")
                    else:
                        await session.say(f"Thank you, {display_name}.")
                
                await session.say("Thank you all. Let's proceed with the discussion.")
            
            else:
                # Regular question
                await session.say(question_text)
                await asyncio.sleep(1)
                
                all_participants = state.get_all_participants()
                
                if all_participants:
                    for i, participant in enumerate(all_participants):
                        should_continue = await ask_participant(
                            state, session, participant,
                            question_text, question_id, question_global_index,
                            is_first=(i == 0),
                            room=room
                        )
                        if not should_continue:
                            return
                        await asyncio.sleep(0.5)
                    
                    await session.say("Thank you all for sharing. Let's move on.")
                else:
                    await session.say("I'll give you a moment to reflect.")
                    await asyncio.sleep(5)
        
        except RuntimeError as e:
            if "closing" in str(e).lower():
                log_event("SESSION_CLOSING", reason="runtime_error")
                return
            raise
        
        state.advance()
        question_global_index += 1
        await asyncio.sleep(1)
    
    # Session complete
    try:
        await session.say("Thank you all so much for participating! Your insights have been incredibly valuable. Have a wonderful day!")
    except RuntimeError:
        pass
    
    log_event("DISCUSSION_COMPLETE")
    state.session_ended = True


async def entrypoint(ctx: agents.JobContext):
    """Main entry point for the moderator agent."""
    room_name = ctx.room.name
    
    log_event("AGENT_ENTRY", room_name=room_name, livekit_url=REDACTED_LIVEKIT_URL)
    
    state = ModeratorState()
    state.room_name = room_name
    
    # Parse session ID
    if room_name.startswith("focusgroup-"):
        parts = room_name.split("-")
        state.session_id = parts[-1] if len(parts) >= 3 else room_name
    elif room_name.startswith("focus-group-"):
        state.session_id = room_name.replace("focus-group-", "")
    else:
        state.session_id = room_name
    
    log_event("SESSION_PARSED", session_id=state.session_id)
    
    guide_file = os.getenv("GUIDE_FILE")
    if guide_file and state.load_guide(guide_file):
        log_event("GUIDE_LOADED", title=state.guide.get('meta', {}).get('title', 'Untitled'))
    else:
        log_event("GUIDE_NOT_LOADED", path=guide_file)
    
    stt = deepgram.STT(model="nova-3")
    
    session = AgentSession(
        stt=stt,
        tts=openai.TTS(voice="echo"),
        vad=silero.VAD.load(),
    )
    
    # ============ CRITICAL: Register transcript handler ============
    # The correct event name is "user_input_transcribed" (NOT "user_speech_committed")
    # UserInputTranscribedEvent has: transcript, is_final, speaker_id, language, created_at
    
    def on_user_input_transcribed(event):
        """
        Called when user speech is transcribed.
        
        Args:
            event: UserInputTranscribedEvent with:
                - transcript: str - the transcribed text
                - is_final: bool - True if this is a final transcript
                - speaker_id: Optional[str]
                - language: Optional[str]
        """
        transcript = getattr(event, 'transcript', '')
        is_final = getattr(event, 'is_final', False)
        
        log_event("USER_INPUT_TRANSCRIBED",
                  transcript=transcript[:80] if transcript else "(empty)",
                  is_final=is_final,
                  agent_speaking=state.agent_speaking,
                  current_state=state.current_question.state.value)
        
        # Only process if we have text and agent isn't speaking
        if not transcript:
            return
            
        if state.agent_speaking:
            log_event("TRANSCRIPT_IGNORED", reason="agent_speaking")
            return
        
        # Check if we're waiting for response
        waiting_states = [
            QuestionState.WAITING_FOR_RESPONSE,
            QuestionState.SILENCE_PROMPTED,
            QuestionState.USER_SPEAKING,
            QuestionState.WRAPUP_REQUESTED,
        ]
        
        if state.current_question.state not in waiting_states:
            log_event("TRANSCRIPT_IGNORED", 
                      reason=f"wrong_state:{state.current_question.state.value}")
            return
        
        # Update legacy QuestionContext (for backward compat)
        state.current_question.add_transcript(transcript)
        state.current_question.cancel_timer()
        
        # Update TurnController (for new turn timing)
        state.turn_controller.on_speech_detected(transcript)
    
    # Register for the correct event name
    session.on("user_input_transcribed", on_user_input_transcribed)
    
    agent = FocusGroupModerator()
    
    log_event("AGENT_CONNECTING", room_name=room_name)
    
    # Start session with retry
    max_retries = 5
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            await session.start(
                room=ctx.room,
                agent=agent,
                room_input_options=RoomInputOptions(close_on_disconnect=False)
            )
            log_event("AGENT_CONNECTED", room_name=room_name, attempt=attempt+1)
            break
        except Exception as e:
            log_event("AGENT_CONNECT_ERROR", room_name=room_name, attempt=attempt+1, error=str(e))
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise
    
    started = await wait_for_session_start(state, session, ctx.room)
    
    if not started:
        log_event("SESSION_NOT_STARTED")
        try:
            await session.say("The session has ended before starting. Goodbye!")
        except RuntimeError:
            pass
        return
    
    # Start background status poller to detect session end
    await state.start_status_poller()
    
    try:
        await run_discussion(state, session, ctx.room)
    except asyncio.CancelledError:
        log_event("DISCUSSION_CANCELLED")
    finally:
        # Ensure shutdown is triggered
        state.trigger_shutdown("discussion_exit")
        
        # Say goodbye if session ended by organizer
        if state.session_ended:
            try:
                await session.say("The session has ended. Thank you everyone for participating. Goodbye!")
            except (RuntimeError, Exception) as e:
                log_event("GOODBYE_FAILED", error=str(e)[:30])
    
    log_event("AGENT_EXIT", room_name=room_name)


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
