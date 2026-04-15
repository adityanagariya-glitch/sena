---
title: Cloud Provider Decision
type: decision
tags: [cloud, blocked, deployment]
sources: ["[[src-technical-decisions]]", "[[src-remaining-questions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Cloud Provider Decision

**Status:** BLOCKED on client input.

## Candidates

| Provider | AU presence | Notes |
|----------|-------------|-------|
| **AWS** | `ap-southeast-2` (Sydney) mature | Bedrock + Claude available. Already in use for [[aws-bedrock]], [[aws-sns]]. |
| **GCP** | `australia-southeast1` (Sydney) | Vertex AI + Gemini Live. Best voice-stack fit if Gemini Live is hosted there. |
| **Azure** | `australiaeast` | Azure OpenAI, Cognitive Services. Viable but less voice-native. |

## Why the client drives this

- SENA integrates into the client team's wider platform
- Ops / support / security / billing concentration on one provider is a strong pull
- Inter-service latency favours same-provider deployment

## De-facto partial state

- **Already on AWS** for Bedrock + SNS (needed for text post-processing)
- If Gemini Live requires GCP, SENA may end up **multi-cloud** by necessity — keep that option open

## Decision gate

Moves to DECIDED when:
1. Client team commits to a provider OR
2. SENA team gets approval to pick independently

## Connections

- Hub: [[Architecture]], [[Client-Requirements]]
- Related: [[deployment-environment]], [[gemini-live-decision]], [[aws-bedrock]]
