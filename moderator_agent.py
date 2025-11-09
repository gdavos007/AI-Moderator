"""
LiveKit Voice Agent – Focus Group Moderator
Broad-based: loads any JSON "guidestruct" and runs the session.
Requires: OPENAI_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY
Optional: GUIDE_FILE=/path/to/guidestruct.json
"""

from dotenv import load_dotenv
import asyncio
from livekit import agents
from livekit.agents import Agent, AgentSession
from livekit.agents.llm import function_tool
from livekit.plugins import openai, deepgram, silero, elevenlabs
import json, os, time
from typing import Dict, Any, List, Optional

# --- Load ENV
load_dotenv("/Users/ganeshkrishnan/Documents/Lever AI/.env", override=True)

# --- In-memory "DB" for notes & guide/state
STATE = {
    "guidestruct": None,
    "section_idx": 0,
    "question_idx": 0,
    "section_script_read": False,  # Track if section script has been read
    "checkpoints": [],
    "group_type": os.getenv("GROUP_TYPE", "Mixed"),
    "participants": {},
    "timers": {},
    "expected_participants": None,
    "labels": [],
    "last_function_call": None,  # Track last function to prevent duplicates
    "function_call_count": 0     # Count functions called this turn
}


def _agenda_current():
    g = STATE["guidestruct"]
    if not g: return None, None
    secs = g.get("sections", [])
    si = STATE["section_idx"]
    qi = STATE["question_idx"]
    sec = secs[si] if si < len(secs) else None
    q = (sec.get("questions", []) if sec else [])
    q = q[qi] if qi < len(q) else None
    return sec, q

def _advance_route_enforce_required():
    """Advance, but enforce that required questions are NEVER skipped."""
    g = STATE["guidestruct"]
    secs = g.get("sections", [])
    si = STATE["section_idx"]
    qi = STATE["question_idx"]
    
    sec = secs[si] if si < len(secs) else None
    if not sec:
        return
    
    questions = sec.get("questions", [])
    
    # Always move to next question in current section
    if qi + 1 < len(questions):
        STATE["question_idx"] += 1
        STATE["section_script_read"] = True  # Once we move to next question, script has been read
    else:
        # Move to next section only after all questions done
        STATE["section_idx"] += 1
        STATE["question_idx"] = 0
        STATE["section_script_read"] = False  # Reset for new section

def _section_is_included(sec: Dict[str, Any]) -> bool:
    routing = sec.get("routing", {})
    include = routing.get("include_if_group")
    if not include:
        return True
    return STATE["group_type"] in include

def _get_next_required_question():
    """Get next question, skipping only sections that fail routing."""
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

# --- TOOLS ---

@function_tool
async def set_participants_count(count: int):
    """Set the number of attendees and generate labels A..N accordingly."""
    count = max(1, min(24, int(count)))
    labels = [chr(ord('A') + i) for i in range(count)]
    STATE["expected_participants"] = count
    STATE["labels"] = labels
    for lb in labels:
        STATE["participants"].setdefault(lb, {"id": lb, "label": lb, "turns": 0, "talk_time_ms": 0, "consented": None})
    print(f"[moderator] Participants set: {count} ({', '.join(labels)})")
    return {"ok": True, "count": count, "labels": labels}

@function_tool
async def ask_question_from_guide() -> Dict[str, Any]:
    """Ask the current question from the discussion guide verbatim. 
    This is the ONLY way to ask a question."""
    sec, q = _agenda_current()
    if not q:
        return {"ok": False, "error": "No current question"}
    
    question_text = q.get("text", "")
    question_id = q.get("id", "")
    question_type = q.get("type", "question")
    
    print(f"[moderator] Asking question {question_id}: {question_text[:60]}...")
    
    return {
        "ok": True, 
        "question_id": question_id,
        "question_text": question_text,
        "question_type": question_type,
        "should_speak": True
    }

@function_tool
async def route_next_question() -> Dict[str, Any]:
    """Advance to the next question and return its ID."""
    # Prevent multiple calls in sequence
    if STATE.get("last_function_call") == "route_next_question":
        print("[moderator] WARNING: Blocked duplicate route_next_question() call")
        return {"ok": False, "error": "Already routed. Wait for next question."}
    
    _advance_route_enforce_required()
    sec, q = _agenda_current()
    
    # Skip sections that fail routing
    while sec and not _section_is_included(sec):
        _advance_route_enforce_required()
        sec, q = _agenda_current()
    
    STATE["last_function_call"] = "route_next_question"
    
    if not sec:
        print("[moderator] Guide complete!")
        return {"ok": True, "done": True, "message": "Guide complete"}
    
    if not q:
        print(f"[moderator] Moving to next section: {sec.get('id')}")
        return {"ok": True, "next_section": sec.get("id")}
    
    print(f"[moderator] Advancing to question {q.get('id')}")
    return {
        "ok": True, 
        "next_section": sec.get("id"),
        "next_question_id": q.get("id"),
    }

@function_tool
async def ask_clarifying_followup(followup: str) -> Dict[str, Any]:
    """Ask ONE brief clarifying question (max 30 words)."""
    # Prevent multiple follow-ups in a row
    if STATE.get("last_function_call") == "ask_clarifying_followup":
        print("[moderator] WARNING: Blocked duplicate ask_clarifying_followup() call. Moving to next question instead.")
        return await route_next_question()
    
    if len(followup.split()) > 30:
        return {"ok": False, "error": "Followup must be ≤30 words"}
    
    print(f"[moderator] Followup: {followup[:50]}...")
    STATE["last_function_call"] = "ask_clarifying_followup"
    return {"ok": True, "followup": followup}

@function_tool
async def timer_start(label: str, minutes: float):
    """Start a named countdown timer."""
    end_ts = time.time() + minutes * 60.0
    STATE["timers"][label] = end_ts
    return {"ok": True, "label": label, "ends_at": end_ts}

@function_tool
async def timer_stop(label: str = ""):
    """Stop a named countdown timer."""
    if label and label in STATE["timers"]:
        STATE["timers"].pop(label, None)
    elif not label:
        STATE["timers"].clear()
    return {"ok": True}

@function_tool
async def workbook_show(card_id: str):
    """Display a workbook card by id."""
    print(f"[moderator] Show workbook card: {card_id}")
    return {"ok": True, "card_id": card_id}

@function_tool
async def call_on(participant_id: str):
    """Invite a specific participant by label."""
    return {"ok": True, "participant_id": participant_id}

@function_tool
async def consent_record(participant_id: str, response: str):
    """Record consent for a participant."""
    p = STATE["participants"].setdefault(participant_id, {"id": participant_id, "label": participant_id, "turns": 0})
    resp = (response or "").strip().lower()
    p["consented"] = resp in {"yes", "y", "i consent", "consent", "yep", "yeah"}
    print(f"[moderator] Consent recorded: {participant_id} = {p['consented']}")
    return {"ok": True, "participant_id": participant_id, "consented": p["consented"]}

@function_tool
async def note_tag(topic: str, quote: str, speaker: str, sentiment: str = "mixed"):
    """Append a tagged note."""
    return {"ok": True, "topic": topic, "speaker": speaker, "sentiment": sentiment, "len": len(quote)}

@function_tool
async def summary_topic(section_id: str):
    """Create a summary of a section."""
    return {"ok": True, "section_id": section_id}

@function_tool
async def export_snapshot():
    """Export running notes."""
    return {"ok": True}


TOOLS = [
    set_participants_count,
    ask_question_from_guide,
    ask_clarifying_followup,
    route_next_question,
    timer_start, timer_stop,
    workbook_show, call_on, consent_record,
    note_tag, summary_topic, export_snapshot
]

# --- MODERATOR AGENT ---

MODERATOR_SYSTEM = """You are a professional Focus Group Moderator. Follow these rules EXACTLY and STRICTLY:

CRITICAL: You may call AT MOST ONE function per turn. After calling any function, STOP immediately and do not call any more functions.

STRICT EXECUTION FLOW:
1. If instructed to read a script, read it aloud naturally and clearly, then call ask_question_from_guide()
2. If instructed to ask a question, call ask_question_from_guide()
3. Listen carefully to the participant's full response
4. After they finish: If the response seems incomplete, call ask_clarifying_followup() ONCE (max 30 words) and STOP
5. If the response seems complete, call route_next_question() and STOP
6. Repeat from step 1

ABSOLUTE RULES - DO NOT VIOLATE:
- NEVER call more than one function per turn
- Always read scripts in a natural, warm tone when instructed
- Wait for the participant to finish speaking before deciding to ask a follow-up
- When in doubt, move forward (call route_next_question()) rather than ask more follow-ups
- Do not skip questions or sections
- Never generate your own questions - only use the discussion guide

TIMING:
- Give participants plenty of time to think and speak
- Do not rush through answers
- If there is silence, wait longer before proceeding"""

class Moderator(Agent):
    def __init__(self, tools=None):
        super().__init__(instructions=MODERATOR_SYSTEM, tools=(tools or []))

def _build_turn_instructions() -> str:
    """Build focused instructions for the current turn."""
    if not STATE["guidestruct"]:
        return "No guide loaded. Wait for guide to be provided."
    
    # STEP 1: Get participant count if not set
    if STATE["expected_participants"] is None:
        return """Call set_participants_count() with the number of participants attending (1-24). 
        Do not proceed until you call this function."""
    
    # STEP 2: Get current question
    sec, q = _get_next_required_question()
    
    # Skip sections that fail routing
    while sec and not _section_is_included(sec):
        _advance_route_enforce_required()
        sec, q = _get_next_required_question()
    
    # STEP 3: If no more sections, close
    if not sec:
        return """The discussion guide is now complete. 
        Thank all participants for their time, tell them the incentives will be distributed, and end the session politely.
        Do not ask any more questions."""
    
    # STEP 4: If no question in section, something is wrong
    if not q:
        return f"""ERROR: Section {sec.get('id')} has no questions. Call route_next_question() immediately."""
    
    # STEP 5: Build context for this question
    section_title = sec.get("title", "")
    section_id = sec.get("id", "")
    section_script = sec.get("script_md", "")
    question_id = q.get("id", "")
    question_text = q.get("text", "")
    question_type = q.get("type", "question")
    question_script = q.get("script_md", "")
    
    lines = [
        f"=== SECTION: {section_id} ===",
        f"Question: {question_id} ({question_type})",
    ]
    
    # CRITICAL: If this is the first question in a section AND the section has a script, read it FIRST
    if STATE["question_idx"] == 0 and section_script and not STATE["section_script_read"]:
        lines.append(f"FIRST, read this script aloud to participants (speak naturally and warmly):")
        lines.append(f"---")
        lines.append(f"{section_script}")
        lines.append(f"---")
        lines.append(f"After reading the script, then ask the question below.")
        lines.append(f"")
    
    # Then handle the question
    if question_type == "info" and question_script:
        # Info-type question: just read the script
        lines.append(f"Read this information aloud to participants:")
        lines.append(f"{question_script}")
        lines.append(f"After reading, call route_next_question() immediately.")
    elif question_type == "rollcall":
        lines.append(f"ROLLCALL - Call each participant by their label and wait for consent:")
        lines.append(f"Say: \"{question_text}\"")
        lines.append(f"Labels to call: {', '.join(STATE['labels'])}")
        lines.append(f"Call ask_question_from_guide() now.")
    elif question_type == "closing":
        lines.append(f"CLOSING - Read this to the participants:")
        lines.append(f"{question_script}")
        lines.append(f"After reading, call route_next_question() immediately.")
    elif question_text:
        lines.append(f"Ask this question verbatim:")
        lines.append(f"\"{question_text}\"")
        lines.append(f"Call ask_question_from_guide() now and wait for their response.")
    
    lines.append("")
    lines.append(f"IMPORTANT: Call exactly ONE function. Do not call multiple functions.")
    
    return "\n".join(lines)


async def entrypoint(ctx: agents.JobContext):
    """Main entry point for the moderator agent."""
    
    # Initialize session
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(model=os.getenv("LLM_CHOICE", "gpt-4o-mini")),
        tts=openai.TTS(voice="echo"),
        vad=silero.VAD.load(),
    )

    agent = Moderator(tools=TOOLS)
    await session.start(room=ctx.room, agent=agent)
    print("[moderator] Agent session started")

    # Load guide
    guide_file = os.getenv("GUIDE_FILE")
    if guide_file and os.path.exists(guide_file):
        with open(guide_file, "r", encoding="utf-8") as f:
            guide = json.load(f)
        STATE["guidestruct"] = guide
        STATE["section_idx"] = 0
        STATE["question_idx"] = 0
        STATE["section_script_read"] = False
        print(f"[moderator] Loaded guide: {guide.get('meta', {}).get('title', 'Untitled')}")
        
        # WORKAROUND: Set a default participant count
        print("[moderator] Requesting participant count from organizer...")
        await session.generate_reply(
            instructions="""Greet everyone and ask the organizer: "How many participants are joining us today?" 
            Wait for their answer, then call set_participants_count() with that number."""
        )
        
        # Wait for agent response
        await asyncio.sleep(2)
        
        # If participant count still not set, use a default
        if STATE["expected_participants"] is None:
            print("[moderator] Setting default participant count to 6")
            await set_participants_count(6)
        
        # Add delay
        await asyncio.sleep(1)
        
        # Start the main discussion immediately
        print("[moderator] Starting discussion flow...")
        await session.generate_reply(
            instructions="""The focus group is now starting. Begin with the Welcome & Consent section."""
        )
    else:
        print("[moderator] ERROR: No guide file found")
        return

    # Main loop
    try:
        iteration = 0
        while True:
            iteration += 1

            # Reset function call tracking for this turn
            STATE["last_function_call"] = None

            turn_instructions = _build_turn_instructions()
            
            print(f"\n[moderator] === TURN {iteration} ===")
            print(f"State: section={STATE['section_idx']}, question={STATE['question_idx']}, script_read={STATE['section_script_read']}")
            print(f"Instructions: {turn_instructions[:100]}...")
            
            await session.generate_reply(instructions=turn_instructions)
            
            # LONGER WAIT - Give participants time to speak and agent time to process
            await asyncio.sleep(4.0)
            
    except RuntimeError as e:
        if "AgentSession is closing" not in str(e):
            print(f"[moderator] ERROR: {e}")
            raise


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))

