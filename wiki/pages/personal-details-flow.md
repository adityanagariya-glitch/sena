---
title: Personal Details Flow
type: concept
tags: [voice, flow, personal-details, form]
sources: ["[[src-flow-b]]", "[[src-architecture-audit]]", "CLAUDE.md"]
created: 2026-04-16
updated: 2026-04-16
---

# Personal Details Flow

A parallel voice-guided flow for capturing participant personal details, running alongside (or independently from) [[flow-b-voice-dictation]]. Uses the same voice infrastructure but a different prompt context and output schema.

## API endpoints

```
POST /v1/voice/personal-details/session       — start session
POST /v1/voice/personal-details/session/turn  — process voice turn
POST /v1/voice/personal-details/session/end   — end session, return collected fields
```

All endpoints require `support_worker`, `manager`, or `admin` role.

## Output schema

Unlike Flow B (which produces free-form case note text), this flow returns structured field-value pairs:

```json
{
  "fields": { "name": "...", "dob": "...", "ndis_number": "..." },
  "missing_fields": ["emergency_contact"],
  "completeness_score": 0.85,
  "agent_reply": "Got it. What is the emergency contact name?"
}
```

The agent asks targeted questions to collect missing fields until `completeness_score` reaches threshold or the session ends.

## Architecture

- Uses [[aws-bedrock]] (Claude 3.5 Sonnet) for structured extraction, same as Flow B
- Session state held in [[redis-usage]] with same TTL/key conventions
- Rate limiting applied per-turn (same as Flow B, `rate_limit_turn_per_minute`)
- No LiveKit session needed — can operate from plain text transcript input

## Relationship to Flow B

| Dimension | Flow B | Personal Details Flow |
|-----------|--------|-----------------------|
| Output | Narrative case note (SOAP) | Structured field-value pairs |
| Prompt style | Open dictation with guided questions | Targeted field collection |
| Typical length | Multiple turns | Short (5-10 fields) |
| Approval required | Yes (human-in-the-loop) | Currently unclear — see [[open-questions]] |

## Connections

- Hub: [[Architecture]]
- Related: [[flow-b-voice-dictation]], [[voice-service]], [[support-worker]], [[ndis-participant]]
- Infrastructure: [[aws-bedrock]], [[redis-usage]]
- Open: [[open-questions]] — approval workflow for personal details TBD
