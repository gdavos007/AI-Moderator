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

# --- In-memory “DB” for notes & guide/state
STATE = {
    "guidestruct": None,
    "section_idx": 0,
    "question_idx": 0,
    "checkpoints": [],
    "group_type": os.getenv("GROUP_TYPE", "Mixed"),
    "participants": {},
    "timers": {},
    "expected_participants": None,   #attendance gate
    "labels": []                     #A...N labels
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

def _advance_route():
    g = STATE["guidestruct"]; secs = g.get("sections", [])
    si, qi = STATE["section_idx"], STATE["question_idx"]
    sec = secs[si] if si < len(secs) else None
    if not sec:
        return
    # next question
    if qi + 1 < len(sec.get("questions", [])):
        STATE["question_idx"] += 1
    else:
        # next section
        STATE["section_idx"] += 1
        STATE["question_idx"] = 0

def _section_is_included(sec: Dict[str, Any]) -> bool:
    routing = sec.get("routing", {})
    include = routing.get("include_if_group")
    if not include:
        return True
    return STATE["group_type"] in include

# ----------------- Tools (model can call these) -----------------

@function_tool
async def timer_start(label: str, minutes: float):
    """Start a named countdown timer."""
    end_ts = time.time() + minutes * 60.0
    STATE["timers"][label] = end_ts
    return {"ok": True, "label": label, "ends_at": end_ts}

@function_tool
async def timer_stop(label: str = ""):
    """Stop a named countdown timer (or all if none)."""
    if label and label in STATE["timers"]:
        STATE["timers"].pop(label, None)
    elif not label:
        STATE["timers"].clear()
    return {"ok": True}

@function_tool
async def route_next():
    """Advance to the next question/section following the guide."""
    _advance_route()
    sec, q = _agenda_current()
    return {"ok": True, "section": sec.get("id") if sec else None, "question": q.get("id") if q else None}

@function_tool
async def ask_question_from_guide() -> Dict[str, Any]:
    """Ask the current question from the discussion guide verbatim. 
    This is the ONLY way to ask a question."""
    sec, q = _agenda_current()
    if not q:
        return {"ok": False, "error": "No current question"}
    
    question_text = q.get("text", "")
    question_id = q.get("id", "")
    
    # Return the question – your TTS layer speaks this
    return {
        "ok": True, 
        "question_id": question_id,
        "question_text": question_text,
        "should_speak": True
    }

@function_tool
async def ask_clarifying_followup(followup: str) -> Dict[str, Any]:
    """Ask ONE brief clarifying question (max 30 words) about the current response.
    After this, you MUST call route_next_question()."""
    if len(followup.split()) > 30:
        return {"ok": False, "error": "Followup must be ≤30 words"}
    return {"ok": True, "followup": followup}

@function_tool
async def workbook_show(card_id: str):
    """Display a workbook card by id (UI responsibility lives in your app)."""
    # Here we just acknowledge; your UI layer should listen for this call.
    return {"ok": True, "card_id": card_id}

@function_tool
async def call_on(participant_id: str):
    """Invite a specific participant (unmute/address by label)."""
    return {"ok": True, "participant_id": participant_id}

@function_tool
async def consent_record(participant_id: str, response: str):
    """Record consent 'yes' or 'no' for a participant."""
    # Minimal store; real impl should map from track or auth ID
    p = STATE["participants"].setdefault(participant_id, {"id": participant_id, "label": participant_id, "turns": 0, "talk_time_ms": 0})
    resp = (response or "").strip().lower()
    p["consented"] = resp in {"yes", "y", "i consent", "consent", "yep", "yeah"}
    return {"ok": True, "participant_id": participant_id, "consented": p["consented"]}

@function_tool
async def note_tag(topic: str, quote: str, speaker: str, sentiment: str = "mixed"):
    """Append a tagged note for later export/analysis."""
    # In practice write to DB; here we just acknowledge
    return {"ok": True, "topic": topic, "speaker": speaker, "sentiment": sentiment, "len": len(quote)}

@function_tool
async def summary_topic(section_id: str):
    """Create a brief summary of a section (the model should populate text in 'say')."""
    return {"ok": True, "section_id": section_id}

@function_tool
async def export_snapshot():
    """Export running notes/summaries (stub)."""
    return {"ok": True}

@function_tool
async def set_participants_count(count: int):
    """Set the number of attendees and generate labels A..N accordingly."""
    count = max(1, min(24, int(count)))  # sane bounds
    labels = [chr(ord('A') + i) for i in range(count)]
    STATE["expected_participants"] = count
    STATE["labels"] = labels
    # Seed participants dict
    for lb in labels:
        STATE["participants"].setdefault(lb, {"id": lb, "label": lb, "turns": 0, "talk_time_ms": 0, "consented": None})
    return {"ok": True, "count": count, "labels": labels}



TOOLS = [
    timer_start, timer_stop, 
    ask_question_from_guide,      # NEW
    ask_clarifying_followup,       # NEW
    route_next,                    # Keep original
    workbook_show, call_on, consent_record, 
    note_tag, summary_topic, export_snapshot, set_participants_count
]

# ----------------- The Moderator Agent -----------------

MODERATOR_SYSTEM = """You are a Focus Group Moderator. Follow these rules EXACTLY:

STRICT FLOW:
1. To ask the current question: ONLY call ask_question_from_guide()
2. After the participant responds, you may call ask_clarifying_followup() ONCE (max 30 words)
3. When you're done with this question, MUST call route_next_question()
4. Repeat steps 1-3

CRITICAL RULES:
- You are NOT allowed to ask questions that are not from the guide.
- You MUST use ask_question_from_guide() before asking anything.
- Do NOT generate question text yourself – the tool provides it.
- If you feel the need to ask something off-guide, use ask_clarifying_followup() (max 30 words).
- After EVERY follow-up, immediately call route_next_question().

Do not deviate. Do not improvise. Use the tools exactly."""

class Moderator(Agent):
    def __init__(self, tools=None):
        super().__init__(instructions=MODERATOR_SYSTEM, tools=(tools or []))

def _build_turn_instructions() -> str:
    if not STATE["guidestruct"]:
        return "No guide loaded. Error: need guide."
    
    if STATE["expected_participants"] is None:
        return "Call set_participants_count() with the number of attendees (1-24)."
    
    sec, q = _agenda_current()
    while sec and not _section_is_included(sec):
        _advance_route()
        sec, q = _agenda_current()
    
    if not sec or not q:
        return "Guide complete. Conclude the session and thank participants."
    
    # MINIMAL context – just confirm what to do next
    return f"Current section: {sec.get('id')}. Current question ID: {q.get('id')}. Call ask_question_from_guide() now."

async def entrypoint(ctx: agents.JobContext):
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(model=os.getenv("LLM_CHOICE", "gpt-4o-mini")),
        tts=openai.TTS(voice="echo"),
        vad=silero.VAD.load(),
    )

    agent = Moderator(tools=TOOLS)
    await session.start(room=ctx.room, agent=agent)

    guide_file = os.getenv("GUIDE_FILE")
    if guide_file and os.path.exists(guide_file):
        with open(guide_file, "r", encoding="utf-8") as f:
            guide = json.load(f)
        STATE["guidestruct"] = guide
        STATE["section_idx"] = 0
        STATE["question_idx"] = 0
        
        # Ask for attendance
        await session.generate_reply(
            instructions="Ask how many participants are attending (1-24), then call set_participants_count() with that number."
        )
    
    # Main loop – simpler, just refresh context each turn
    try:
        while True:
            turn_instructions = _build_turn_instructions()
            await session.generate_reply(instructions=turn_instructions)
            await asyncio.sleep(0.5)  # Small delay for tool processing
    except RuntimeError as e:
        if "AgentSession is closing" not in str(e):
            raise

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))

#tts=elevenlabs.TTS(voice_id=os.getenv("ELEVEN_VOICE_ID","5kMbtRSEKIkRZSdXxrZg"),model=os.getenv("ELEVEN_MODEL","eleven_flash_v2_5"),),
