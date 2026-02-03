# Voice-Agent Focus Group Moderator (LiveKit + n8n) — Prototype

A Zoom-like web experience powered by LiveKit where an AI Voice Agent moderates qualitative focus groups using a JSON discussion guide, enforces turn-taking, and produces post-session deliverables (speaker-labeled transcript + takeaways + quotes + recommendations), delivered via email/DOCX.

## Why this exists
This prototype demonstrates:
- A real-time "room" experience (tiles, roster, join link)
- An AI moderator that runs a discussion guide and manages group dynamics
- Automatic post-session reporting with quotes and timestamps

## ⚠️ “Vibe Coding” guardrails (inspired by research)
LLM-driven building is inherently stochastic—debugging/refinement can feel like “rolling the dice.” :contentReference[oaicite:5]{index=5}  
This repo enforces safeguards to keep the system stable and debuggable:

### Guardrail A: Small changes, always
- Break features into bite-sized tasks (no giant prompts that rewrite the world). :contentReference[oaicite:6]{index=6}
- Prefer tight diffs. If the agent proposes large refactors, split into steps.

### Guardrail B: “Green = proceed” (tests + lint + checkpoints)
Vibe coders rein in stochastic changes using undo/version control, small edits, tests, and linters. :contentReference[oaicite:7]{index=7}  
This repo requires:
- `make test` (or equivalent) passes before merging
- lint/type checks on key services
- frequent “green commits” (checkpoint commits)

### Guardrail C: Anti-fixation exploration
Vibe coders often anchor on the first generated output (design fixation). :contentReference[oaicite:8]{index=8}  
Before committing a major architecture or flow:
- generate 2–3 alternatives (even rough)
- choose explicitly and record why

### Guardrail D: Context discipline
Vibe coders actively manage context size and struggle to track what’s been shared. :contentReference[oaicite:9]{index=9}  
We treat “context” as a first-class artifact:
- keep a session “working memory” summary
- store a prompt/decision ledger for traceability

## Core demo (what you can show in <5 minutes)
1) Organizer creates a session → gets a shareable join link
2) Participants join, enter name (and optionally email)
3) Organizer confirms attendance → clicks **Start**
4) AI moderator runs 3–5 questions from `discussion_guide.json`
   - calls on participants round-robin
   - keeps everyone else muted (or requests self-unmute if remote unmute disabled)
   - handles silence, “repeat question”, off-topic, and long-winded answers
5) End session → report generated + emailed (DOCX + email body summary)

## Features (Prototype Scope)

### Real-time session
- Zoom-like UI with tiles & roster
- “Start session” gate (moderator waits until organizer clicks Start)
- Turn-taking (only one speaker at a time)
- Raise-hand signal (UI → agent acknowledgement)
- Disconnect/reconnect continuity (identity-based rejoin)

### Moderator behaviors
- Time-boxed, neutral-friendly tone
- Gently cuts off long answers
- Handles silence (“we’ll move on if no one responds”)
- Off-topic nudges back to guide
- “I don’t know” encouragement
- “Repeat the question” verbatim

### Outputs after session
- Speaker-labeled transcript with timestamps
- Key takeaways + example quotes
- Recommendations / next steps
- Delivery: email and/or DOCX

## Architecture (high-level)
- apps/web/       Zoom-like UI (LiveKit components, roster, Start, raise-hand)
- services/api/   session lifecycle, tokens, state, webhooks, artifacts
- services/agent/ moderator agent (guide runner + STT/TTS + turn-taking)
- workflows/n8n/  invite + report delivery

## Observability & Benchmarks (LangSmith)

Tracing is controlled via environment variables loaded from `.env` (see `.env.example`).
To enable, set `LANGSMITH_TRACING=true` and provide `LANGSMITH_API_KEY`. Traces will appear under the LangSmith project named by `LANGSMITH_PROJECT` (default: `playground`).

Quick check:
- Run the agent locally
- Start a short session
- Confirm the session trace appears in LangSmith under the configured project


Run eval:
- python services/agent/eval/run_eval.py

## Security & privacy (prototype guidance)
- Show an explicit “recording/transcription” notice
- Avoid logging raw PII where possible
- Store artifacts securely; delete after demo window

## Local demo (happy path)
Run the minimal API + web UI in two terminals.

### Terminal 1: API
```
cd "services/api"
npm install
npm run dev
```

### Terminal 2: Web UI
```
cd "apps/web"
npm install
npm run dev
```

Open the URL printed by Vite (default: `http://localhost:5173`).
