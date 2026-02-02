# Product Requirements Document (PRD)
## Voice-Agent Focus Group Moderator (Prototype)

### 1) Summary
Build a Zoom-like multi-participant video room where an AI Voice Agent moderates a qualitative focus group using a JSON discussion guide, enforces turn-taking, and generates post-session deliverables (speaker-labeled transcript + takeaways + quotes + recommendations) delivered via email/DOCX.

### 2) Goals
- Demonstrate a realistic focus group environment (tiles + moderator voice)
- Show strong moderation behaviors (time-boxed, neutral-friendly, handles silence/off-topic)
- Produce high-quality post-session report automatically
- Achieve acceptable perceived latency (<2s preferred for moderation prompts)

### 3) Key risks (from LLM-driven development research)
- Stochastic behavior during refinement/debugging (“rolling the dice”) :contentReference[oaicite:26]{index=26}
- Design fixation: anchoring on first output instead of exploring alternatives :contentReference[oaicite:27]{index=27}
- Context drift: difficulty tracking what has been shared; over-indexing long context :contentReference[oaicite:28]{index=28}

### 4) Non-goals (POC)
- True native integration inside Zoom/Teams meetings
- Full recruiting/panel management system
- Perfect diarization from mixed audio (we rely on per-participant tracks)

### 5) Users & Roles
- Organizer (client): creates session, invites participants, clicks Start, receives report
- Participant: joins, enters name (and optional email), answers when called, can raise hand
- AI Moderator: runs the guide, manages speaking turns, generates report

### 6) Functional Requirements

#### 6.1 Session & Invites
- FR-1: Organizer can create a session and obtain a shareable join link.
- FR-2: Participants can join via link and must enter display name; email optional.
- FR-3: Organizer can see attendance roster in UI.

#### 6.2 Start Gate
- FR-4: Moderator does not begin until organizer clicks Start.
- FR-5: Start action restricted to organizer role.

#### 6.3 Moderation + Turn-taking
- FR-6: Moderator conducts round-table discussion from JSON guide.
- FR-7: Only one participant answers at a time; others muted (or asked to self-unmute if remote unmute disabled).
- FR-8: Participant can raise hand; moderator acknowledges and queues them.
- FR-9: Moderator is time-boxed per question and per participant (configurable).

#### 6.4 Conversation Handling
- FR-10: Long-winded: moderator interrupts politely and asks to wrap up.
- FR-11: Silence: moderator acknowledges and moves on after threshold.
- FR-12: Off-topic: moderator redirects kindly to topic.
- FR-13: “I don’t know”: moderator encourages best-effort response.
- FR-14: “Repeat question”: moderator repeats verbatim.

#### 6.5 Resilience
- FR-15: If participant disconnects and reconnects, continue session at current point.
- FR-16: Participant identity persists across reconnects.

#### 6.6 Outputs & Delivery
- FR-17: Produce speaker-labeled transcript with timestamps.
- FR-18: Produce key takeaways with supporting quotes where possible.
- FR-19: Produce recommendations / next steps.
- FR-20: Deliver report via email/DOCX to participants who provided email.

### 7) Stochasticity management requirements (must-have)
Vibe-coding studies show practitioners mitigate stochastic changes using undo/version control, small changes, tests, and linters. :contentReference[oaicite:29]{index=29}

- SR-1: The repo must support frequent checkpointing (“green commits”).
- SR-2: Critical flows must have automated tests; tests must be runnable locally.
- SR-3: A “reroll protocol” must exist for repeated failures:
  1) revert to last green checkpoint
  2) reduce scope (smaller task/prompt)
  3) try alternate prompt/model
  4) increase tracing/logging

### 8) Anti-fixation requirements (must-have)
Because fixation on the first output is common. :contentReference[oaicite:30]{index=30}

- AF-1: For any major architectural decision (agent pipeline, report format, state model), generate 2–3 alternatives.
- AF-2: Record chosen alternative + rationale in docs/decisions/.

### 9) Context & decision tracking (must-have)
Because tracking what’s been shared becomes difficult and context must be managed. :contentReference[oaicite:31]{index=31}

- CD-1: Maintain a session “prompt/decision ledger” with:
  - guide hash/version
  - key decisions (speaker changes, cutoffs, topic redirects)
  - references to trace ids
- CD-2: Agent prompts must use short “working memory” summaries + quoted snippets only.

### 10) Observability & QA
- O-1: All LLM calls traced to LangSmith when enabled.
- O-2: Store deterministic session events (start, question transitions, speaker changes, raise-hand).
- O-3: Offline evaluation dataset covering:
  - silence
  - off-topic
  - long-winded cutoff
  - repeat question
  - “I don’t know”
  - (meta) alternative generation for major decisions

### 11) Performance Requirements
- PR-1: Moderator turn-taking prompts should feel <2 seconds perceived latency when possible.
- PR-2: Report generation should complete within a demo window (target: <2 minutes for short sessions).

### 12) Milestones (suggested)
- M1: Room + roster + Start gate end-to-end
- M2: Agent turn-taking + guide runner + raise-hand
- M3: Transcript + timestamps + basic report
- M4: Email/DOCX delivery via API or n8n
- M5: LangSmith tracing + offline eval set + reroll protocol documented
