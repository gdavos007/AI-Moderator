"""
LiveKit Voice Agent – Focus Group Moderator
Broad-based: loads any JSON "guidestruct" and runs the session.
Requires: OPENAI_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY
Optional: GUIDE_FILE=/path/to/guidestruct.json
"""

from dotenv import load_dotenv
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
    "guidestruct": None,   # dict
    "section_idx": 0,
    "question_idx": 0,
    "checkpoints": [],
    "group_type": os.getenv("GROUP_TYPE", "Mixed"),
    "participants": {},    # trackSid -> {id,label,talk_time_ms,turns,consented}
    "timers": {},          # label -> end_ts
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
def timer_start(label: str, minutes: float):
    """Start a named countdown timer."""
    end_ts = time.time() + minutes * 60.0
    STATE["timers"][label] = end_ts
    return {"ok": True, "label": label, "ends_at": end_ts}

@function_tool
def timer_stop(label: str = ""):
    """Stop a named countdown timer (or all if none)."""
    if label and label in STATE["timers"]:
        STATE["timers"].pop(label, None)
    elif not label:
        STATE["timers"].clear()
    return {"ok": True}

@function_tool
def route_next():
    """Advance to the next question/section following the guide."""
    _advance_route()
    sec, q = _agenda_current()
    return {"ok": True, "section": sec.get("id") if sec else None, "question": q.get("id") if q else None}

@function_tool
def workbook_show(card_id: str):
    """Display a workbook card by id (UI responsibility lives in your app)."""
    # Here we just acknowledge; your UI layer should listen for this call.
    return {"ok": True, "card_id": card_id}

@function_tool
def call_on(participant_id: str):
    """Invite a specific participant (unmute/address by label)."""
    return {"ok": True, "participant_id": participant_id}

@function_tool
def consent_record(participant_id: str, response: str):
    """Record consent 'yes' or 'no' for a participant."""
    # Minimal store; real impl should map from track or auth ID
    p = STATE["participants"].setdefault(participant_id, {"id": participant_id, "label": participant_id, "turns": 0, "talk_time_ms": 0})
    p["consented"] = (response.lower() == "yes")
    return {"ok": True, "participant_id": participant_id, "consented": p["consented"]}

@function_tool
def note_tag(topic: str, quote: str, speaker: str, sentiment: str = "mixed"):
    """Append a tagged note for later export/analysis."""
    # In practice write to DB; here we just acknowledge
    return {"ok": True, "topic": topic, "speaker": speaker, "sentiment": sentiment, "len": len(quote)}

@function_tool
def summary_topic(section_id: str):
    """Create a brief summary of a section (the model should populate text in 'say')."""
    return {"ok": True, "section_id": section_id}

@function_tool
def export_snapshot():
    """Export running notes/summaries (stub)."""
    return {"ok": True}

@function_tool
def load_guidestruct(guidestruct_json: str = "/Users/ganeshkrishnan/Documents/Lever AI/guidestruct.json", from_file: str = ""):
    """
    Load a discussion guide into memory.
    Provide either `guidestruct_json` (raw JSON string pasted in chat) or `from_file` (server path).
    """
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            guide = json.load(f)
    else:
        guide = json.loads(guidestruct_json)

    # reset state
    STATE["guidestruct"] = guide
    STATE["section_idx"] = 0
    STATE["question_idx"] = 0
    STATE["checkpoints"] = []
    return {"ok": True, "title": guide.get("meta", {}).get("title"), "duration": guide.get("meta", {}).get("duration_minutes")}

TOOLS = [timer_start, timer_stop, route_next, workbook_show, call_on, consent_record, note_tag, summary_topic, export_snapshot, load_guidestruct]

# ----------------- The Moderator Agent -----------------

MODERATOR_SYSTEM = """You are an impartial, professional qualitative Focus Group Moderator.
Your objectives: (1) obtain consent, (2) enforce ground rules, (3) follow a time-boxed discussion guide (sections/questions/cards),
(4) balance participation, and (5) capture tagged quotes & brief summaries. Remain neutral and nonpartisan.
Avoid persuasion or advocating positions. Anonymize participants (use labels). Keep prompts concise.
When ready to move on, call the tool route_next(). Use workbook_show() before reading a card.
Always return short speakable turns; use tools for control and notes."""

class Moderator(Agent):
    def __init__(self, tools=None):
        super().__init__(instructions=MODERATOR_SYSTEM, tools=(tools or []))

def _build_turn_instructions() -> str:
    """Give the model context for THIS turn from the guide and state."""
    sec, q = _agenda_current()
    if not STATE["guidestruct"]:
        return "No discussion guide loaded. Prompt the organizer to load one via load_guidestruct()."
    # Skip excluded sections
    while sec and not _section_is_included(sec):
        _advance_route()
        sec, q = _agenda_current()
    if not sec:
        return "We have completed the guide. Thank participants, ask for last remarks, and end politely."

    meta = STATE["guidestruct"].get("meta", {})
    sec_title = sec.get("title", "")
    sec_script = sec.get("script_md", "")
    cards = sec.get("cards", [])
    q_text = q.get("text") if q else None
    q_script = q.get("script_md") if q else None

    lines = []
    lines.append(f'Guide: "{meta.get("title","")}" | GroupType: {STATE["group_type"]}')
    lines.append(f'Section: {sec.get("id","")} – {sec_title}')
    if cards:
        lines.append(f'Cards to show now: {", ".join(cards)} (call workbook_show for each before reading content)')
    if sec_script:
        lines.append(f'Section Script: {sec_script}')
    if q_script:
        lines.append(f'Question Script: {q_script}')
    if q_text:
        lines.append(f'Ask: {q_text}')
    lines.append("If this question is answered sufficiently, summarize briefly, then call route_next().")
    return "\n".join(lines)

async def entrypoint(ctx: agents.JobContext):
    # STT/LLM/TTS
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(model=os.getenv("LLM_CHOICE", "gpt-4o-mini")),
        tts=elevenlabs.TTS(
            voice_id=os.getenv("ELEVEN_VOICE_ID","5kMbtRSEKIkRZSdXxrZg"),
            model=os.getenv("ELEVEN_MODEL","eleven_flash_v2_5"),
        ),
        vad=silero.VAD.load(),
    )

    agent = Moderator(tools=TOOLS)  # <-- pass tools to Agent
    # Start
    await session.start(room=ctx.room, agent=Moderator())

    # Option A: auto-load from file if provided
    guide_file = os.getenv("GUIDE_FILE")
    if guide_file and os.path.exists(guide_file):
        await session.generate_reply(
            instructions='Call load_guidestruct(from_file="{path}") then acknowledge.'.format(path=guide_file)
        )
    else:
        # Option B: ask organizer to paste JSON and call the tool
        await session.generate_reply(
            instructions="Welcome the organizer. Ask them to load a discussion guide by calling load_guidestruct() with either `guide_json` (paste) or `from_file`."
        )

    # Main loop: repeatedly prompt the model with current agenda context
    while True:
        turn_ctx = _build_turn_instructions()
        await session.generate_reply(instructions=turn_ctx)
        # LiveKit agents framework will interleave user audio turns and tool calls automatically.
        # You can add a small sleep to avoid hot-looping.
        await agents.aio.sleep(1.0)

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
