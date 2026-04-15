---
title: Flow B Specification (Source)
type: source
raw_path: "archive/Extras/FlowB.md"
ingested: 2026-04-15
tags: [voice, flow-b, dictation, source]
---

# Flow B Specification (Source Summary)

## Key Takeaways

- Flow B = case note dictation user flow (support worker speaks case note post-shift)
- Currently HTTP turn-based: POST /session, POST /session/turn, POST /session/end
- Uses Bedrock (Claude 3.5 Sonnet), LiveKit token exchange, Redis state
- End of session → compile case note → approval queue → SNS event

## Detailed Summary

**User story:** Disability support worker finishes shift, opens app, speaks naturally. System generates structured case note. Worker reviews, edits or approves. Manager/admin approves final version.

**Turn loop:**
1. Client POST /session → LiveKit token + session_id
2. Client streams audio → transcription → POST /session/turn with transcript
3. Bedrock updates draft case note
4. Client POST /session/end → final compile + approval item created + SNS event

**Constraints:**
- All AI output requires human approval ([[human-in-the-loop]])
- Multi-tenant isolation via [[row-level-security]]
- Australian data residency ([[australian-data-residency]])

## Pages Updated

- [[flow-b-voice-dictation]]
- [[voice-service]]
- [[case-notes]]
- [[approval-workflow]]

## Connections

- Hub: [[Architecture]]
- Related: [[src-voice-arch-analysis]], [[src-voice-repo-research]]
