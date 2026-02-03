"""
LiveKit Voice Agent – Focus Group Moderator (TTS-Only Questions)
TTS reads questions, STT captures responses, no LLM in the main loop
Requires: OPENAI_API_KEY, DEEPGRAM_API_KEY, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL
Optional: GUIDE_FILE=/path/to/guidestruct.json
"""

from dotenv import load_dotenv
import asyncio
from livekit import agents
from livekit.agents import Agent, AgentSession
from livekit.plugins import openai, deepgram, silero
import json, os, time
from typing import Dict, Any

# --- Load ENV
load_dotenv("/Users/ganeshkrishnan/Documents/Lever AI/.env", override=True)

# --- In-memory STATE
STATE = {
    "guidestruct": None,
    "section_idx": 0,
    "question_idx": 0,
    "section_script_read": False,
    "group_type": os.getenv("GROUP_TYPE", "Mixed"),
    "expected_participants": None,
    "labels": [],
    "participants": {},
    "current_responses": [],
}


def _agenda_current():
    """Get current section and question"""
    g = STATE["guidestruct"]
    if not g: 
        return None, None
    secs = g.get("sections", [])
    si = STATE["section_idx"]
    qi = STATE["question_idx"]
    sec = secs[si] if si < len(secs) else None
    q = (sec.get("questions", []) if sec else [])
    q = q[qi] if qi < len(q) else None
    return sec, q


def _advance_route():
    """Move to next question"""
    g = STATE["guidestruct"]
    secs = g.get("sections", [])
    si = STATE["section_idx"]
    qi = STATE["question_idx"]
    
    sec = secs[si] if si < len(secs) else None
    if not sec:
        return
    
    questions = sec.get("questions", [])
    
    if qi + 1 < len(questions):
        STATE["question_idx"] += 1
        STATE["section_script_read"] = True
    else:
        STATE["section_idx"] += 1
        STATE["question_idx"] = 0
        STATE["section_script_read"] = False


def _section_is_included(sec: Dict[str, Any]) -> bool:
    """Check if section applies to this group"""
    routing = sec.get("routing", {})
    include = routing.get("include_if_group")
    if not include:
        return True
    return STATE["group_type"] in include


def _get_next_required_question():
    """Get next question, skipping excluded sections"""
    g = STATE["guidestruct"]
    secs = g.get("sections", [])
    si = STATE["section_idx"]
    
    current_sec = secs[si] if si < len(secs) else None
    if current_sec and not _section_is_included(current_sec):
        STATE["section_idx"] += 1
        STATE["question_idx"] = 0
        STATE["section_script_read"] = False
        return _get_next_required_question()
    
    if not current_sec:
        return None, None
    
    qi = STATE["question_idx"]
    q = current_sec.get("questions", [])[qi] if qi < len(current_sec.get("questions", [])) else None
    
    return current_sec, q


# --- MINIMAL AGENT (LiveKit requirement, no LLM used) ---
class Moderator(Agent):
    """Minimal agent - we don't use LLM, just need this for LiveKit compatibility"""
    def __init__(self):
        super().__init__(instructions="", tools=[])


async def entrypoint(ctx: agents.JobContext):
    """Main entry point - TTS only for questions"""
    
    # Initialize session with ONLY STT and TTS (no LLM)
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        tts=openai.TTS(voice="echo"),  # Direct TTS, no LLM
        vad=silero.VAD.load(),
    )
    
    # Create minimal agent for LiveKit compatibility
    agent = Moderator()
    await session.start(room=ctx.room, agent=agent)
    print("[moderator] Session started - TTS/STT only (no LLM)")
    
    # Load guide
    guide_file = os.getenv("GUIDE_FILE")
    if not guide_file or not os.path.exists(guide_file):
        print("[moderator] ERROR: No guide file found")
        await session.say("Error: No discussion guide found.")
        return
    
    with open(guide_file, "r", encoding="utf-8") as f:
        guide = json.load(f)
    STATE["guidestruct"] = guide
    print(f"[moderator] Loaded guide: {guide.get('meta', {}).get('title', 'Untitled')}")
    
    # Get participant count manually
    print("[moderator] Asking for participant count...")
    await session.say("Hello! How many participants are joining us today? Please say just the number.")
    
    # Wait for user to respond
    await asyncio.sleep(4)  # Give time for response
    
    # For now, default to 1 participant (in production, parse STT transcript)
    print("[moderator] Setting participant count to: 1")
    STATE["expected_participants"] = 1
    STATE["labels"] = ["A"]
    STATE["participants"]["A"] = {"id": "A", "label": "A", "consented": None}
    
    await asyncio.sleep(1)
    
    # Main loop - just TTS questions and STT responses
    try:
        turn = 0
        while True:
            turn += 1
            print(f"\n[moderator] === TURN {turn} ===")
            print(f"State: section_idx={STATE['section_idx']}, question_idx={STATE['question_idx']}")
            
            sec, q = _get_next_required_question()
            
            # Skip excluded sections
            while sec and not _section_is_included(sec):
                _advance_route()
                sec, q = _get_next_required_question()
            
            # Check if we're done
            if not sec:
                print("[moderator] Discussion guide complete!")
                await session.say("Thank you very much for participating in this focus group. Your feedback is extremely valuable. You'll receive your incentive as you leave. We really appreciate your time and contributions today.")
                await asyncio.sleep(2)
                break
            
            if not q:
                print(f"[moderator] ERROR: No question in section {sec.get('id')}. Advancing...")
                _advance_route()
                await asyncio.sleep(1)
                continue
            
            question_id = q.get("id", "")
            question_type = q.get("type", "question")
            question_text = q.get("text", "")
            question_script = q.get("script_md", "")
            section_script = sec.get("script_md", "")
            section_id = sec.get("id", "")
            
            print(f"[moderator] Current question ID: {question_id} (type: {question_type})")
            print(f"[moderator] Question text: {question_text[:80] if question_text else 'N/A'}...")
            
            # Handle section script (read once at start of section)
            if STATE["question_idx"] == 0 and section_script and not STATE["section_script_read"]:
                print(f"[moderator] Reading section script for: {section_id}")
                await session.say(section_script)
                STATE["section_script_read"] = True
                await asyncio.sleep(5)
            
            # Speak the question based on type
            print(f"[moderator] >>> ASKING QUESTION: {question_id}")
            
            if question_type == "info":
                # Info-type: just read the script
                print(f"[moderator] Speaking info: {question_script[:80]}...")
                await session.say(question_script)
            elif question_type == "closing":
                # Closing: read the script
                print(f"[moderator] Speaking closing: {question_script[:80]}...")
                await session.say(question_script)
            elif question_type == "rollcall":
                # Rollcall: ask for consent from each person
                print(f"[moderator] Starting rollcall for {len(STATE['labels'])} participant(s)")
                await session.say(question_text)
                for label in STATE["labels"]:
                    await session.say(f"Label {label}, please say yes to consent.")
                    await asyncio.sleep(4)  # Wait for response
            else:
                # Regular question: ask verbatim from guide
                print(f"[moderator] Speaking question: {question_text[:80]}...")
                await session.say(question_text)
            
            # Wait for participant response via STT
            print(f"[moderator] Waiting for response (5 seconds)...")
            await asyncio.sleep(15)  # Give time for user to respond
            
            # Move to next question - DO THIS ONLY ONCE
            print(f"[moderator] <<< ADVANCING FROM {question_id} to next question")
            _advance_route()
            
            # Get the new question for logging
            next_sec, next_q = _get_next_required_question()
            next_question_id = next_q.get("id", "") if next_q else "NONE"
            print(f"[moderator] Next question will be: {next_question_id}")
            
            await asyncio.sleep(5)  # Longer pause between questions
            
    except KeyboardInterrupt:
        print("[moderator] Session ended by user")
    except Exception as e:
        print(f"[moderator] Error: {e}")
        raise


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))

#tts=elevenlabs.TTS(voice_id=os.getenv("ELEVEN_VOICE_ID","5kMbtRSEKIkRZSdXxrZg"),model=os.getenv("ELEVEN_MODEL","eleven_flash_v2_5"),),
