---
title: Prompt + Decision Ledger
---

# Session Ledger

## 2026-01-15 — MVP vertical slice
- Guide hash/version: `discussion_guide.json` (file-based; hash pending)
- Key decisions:
  - Use Vite + React web app and a minimal Node `http` API
  - Implement deterministic raise-hand event payloads (versioned `v1`)
  - Moderator flow is UI-driven with guide items flattened
- Trace ids: N/A (LLM calls not invoked in MVP)
- Notes:
  - No external integrations for MVP (LangSmith/VAPI/email)

# Working Memory (short)
- MVP focuses on lobby, roster, start gate, raise-hand, and guide runner.
- UI messages are small, typed, and versioned for event payloads.
