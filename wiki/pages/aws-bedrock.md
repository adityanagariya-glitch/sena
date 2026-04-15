---
title: AWS Bedrock
type: entity
tags: [aws, llm, external-service, entity]
sources: ["[[src-architecture-audit]]", "[[src-new-plan]]"]
created: 2026-04-15
updated: 2026-04-15
---

# AWS Bedrock

AWS's managed LLM gateway. SENA uses Bedrock's **Claude 3.5 Sonnet** endpoint.

## Where it's used in SENA

- **Case note compilation** — turn conversation transcript into structured case note draft
- **Approval-reasoning summary** — concise summary for manager review UI
- **Personal-details extraction** — pull structured fields out of free-form utterances
- **(Legacy Flow B)** — was the main LLM; now shares responsibility with [[gemini-live-decision]]

## Why Bedrock

- AU region support (`ap-southeast-2` has Claude 3.5 Sonnet)
- Satisfies [[australian-data-residency]] for text post-processing
- No ops burden — Anthropic-grade model behind an AWS IAM boundary
- Pay-per-use pricing suits bursty voice workload

## Integration details

- SDK: `boto3` bedrock-runtime client
- Invocation: message format (Anthropic's messages API via Bedrock)
- Streaming supported but most case note post-processing is single-shot
- Prompts in `sena-ai/services/voice/src/voice/prompts/`

## Risks

- Model deprecation — need to re-evaluate prompts on Claude version bumps
- Cost scaling — case note compilation per shift per worker adds up; batch where possible

## Connections

- Hub: [[Architecture]]
- Related: [[gemini-live-decision]] (complementary), [[voice-service]]
- Source: [[src-architecture-audit]]
