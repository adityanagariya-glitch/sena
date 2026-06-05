---
name: explain
description: Deep explanation of an ML/AI concept, pattern, library, paper, or technology. Use when the user asks "what is X", "explain Y", "how does Z work", "what's the difference between A and B" (educationally, not as a sign-off). Grounds claims in Context7 docs or Playwright-fetched papers.
argument-hint: [concept, library, or paper to explain]
allowed-tools: Read
---

# /explain — Verified Deep Explanation

## Phase 1 — Verify before teaching

This is the cardinal rule of `/explain`: **never explain something you haven't verified.** Stale training data on ML APIs is the #1 source of bad mentorship.

- **Library or framework concept** (e.g., "explain FSDP", "explain LangGraph's checkpointing") → `mcp__context7__resolve-library-id` then `get-library-docs`.
- **Paper or research concept** (e.g., "explain GRPO", "explain MoE routing in DeepSeek") → `mcp__playwright__browser_navigate` to the arxiv link, read the relevant section.
- **Model architecture or HF-specific** (e.g., "what's the difference between Llama-3.1 and Llama-3.3") → use the `huggingface` MCP.
- **General concept with no obvious authoritative source** → answer from first principles, mark anything version-specific as `Unverified:`.

## Phase 2 — Structure (no three-block format here; this is teaching, not review)

Use this shape:

1. **The 30-second version.** One paragraph. The core idea, in plain language. If the user only reads this, they understand the gist.

2. **The mechanism.** *How* it works, not just *what* it is. The math/algorithm/data flow. Use a concrete example with real numbers when possible.

3. **When to use it.** Concrete scenarios where this is the right tool.

4. **When NOT to use it.** Concrete scenarios where it's overkill, premature, or wrong. This is the most-often-skipped section and the most valuable.

5. **Common mistakes.** What juniors get wrong with this, named by name. Cite real code patterns.

6. **What it looks like in production.** Operational concerns — cost, latency, failure modes, monitoring. The textbook version vs the 3-AM-incident version.

7. **Further reading.** 2–3 specific sources (paper, doc page, blog), each with one line on why it's worth reading. Cite URLs from your verification step.

## Hard rules

- **Code snippets must be runnable** against the verified API version. Never hand-write a `transformers.Trainer` call from memory.
- **Math when helpful, prose otherwise.** Equations earn their place by clarifying, not by signaling depth.
- **One concrete example is worth ten abstractions.** "BERT-base has 12 layers, 768 hidden dim, ~110M params" beats "BERT is a transformer."
- **Stop at the level of detail the question implies.** A 1-line question gets a tight explanation; a deep "I want to understand FSDP fully" gets the long form.
- **No padding.** No "I hope this helps!" No "let me know if you have questions!" The follow-up question should be the user's, not yours.
