---
description: Universal rule — apply asymmetric trust whenever an agent or feature operates with retrieved/privileged context (lessons.md, decisions.md, rules autoload, RAG, cross-screen context, schema injection). Positive additions need a citation, negative rejections need a high-confidence anchor. Pattern adapted from SDAR (arXiv:2605.15155, May 2026). Applies to all 14 current agents + future agents + future AI features.
---

# ⚖️ Asymmetric Privileged Trust (SDAR-Inspired)

Source: *Self-Distilled Agentic Reinforcement Learning* (Lu et al., arXiv:2605.15155, 2026-05-14). We don't train models — but the **trust-gating** principle ports directly to inference-time agent reasoning and feature implementation.

## The pattern (one line)

When privileged context (lessons / rules / RAG / past summaries) influences an output, **trust positive recommendations weighted by citation strength, attenuate negative rejections weighted by retrieval quality**.

## Why asymmetric

The SDAR insight: a teacher with privileged context can endorse the student's action *for the right reason* (positive gap) OR reject it *for a stale/wrong reason* (bad retrieval). Symmetric trust treats both equally — and propagates retrieval errors. Asymmetric trust:
- **Positive (teacher says "add X")** → requires a citation: file:line, lesson #, rule path, RAG similarity score. No citation → low trust.
- **Negative (teacher says "don't do Y")** → requires a high-confidence anchor: explicit rule match, `Occurrences: 3+` lesson, deterministic check (lint/type/test). Soft pattern-match alone → attenuate.

## The 3 places this applies

### 1. Agent reasoning (all 14 agents + future)

Every agent loads privileged context (path-scoped rules, lessons.md, decisions.md, prior reviewer findings). Before emitting an output that contradicts the user's plain request OR the canonical principal-engineer rules:

```
Self-check (asymmetric gate):
1. Is this output ADDING something? → cite which privileged context produced it (rule file:section, lesson #, decision date). No citation = drop.
2. Is this output REJECTING something the user asked for? → name the high-confidence anchor (rule path, 3×-promoted lesson, hook block, test failure). Soft signal alone = surface to user, don't auto-reject.
```

**Per-agent application** (drop into each agent's `<principal_engineer_mode>` "For <agent>:" line):

| Agent | Positive citation source | Negative anchor required |
|-------|--------------------------|--------------------------|
| `sena-planner` | `pyproject.toml` dep / repo Grep hit / past plan in ARCHIVE.md | Explicit rule conflict (NDIS / tenant) — not "feels risky" |
| `sena-task-breaker` | Planner's files-to-touch list | Dependency cycle detected — not "could be split more" |
| `sena-implementer` | Path-scoped rule autoloaded for the file type | ruff/mypy failure — not "feels non-idiomatic" |
| `sena-business-reviewer` | NDIS rule violation w/ specific clause | Pattern-match on past finding (low trust unless 3×) |
| `sena-security-reviewer` | Tenant key missing, `assert_session_owner` absent, secret committed | "Looks suspicious" alone — must cite OWASP or auto-block signature |
| `sena-bug-fixer` | Reviewer finding w/ file:line | Cannot expand scope beyond named files |
| `sena-optimization-reviewer` | Profile / benchmark / N+1 grep hit | "Could be faster" without measurement |
| `sena-cleaner` | ruff/mypy output, debug-print grep | "Code smell" without lint rule |
| `sena-git-committer` | Files in diff, decisions.md entry from this cycle | Cannot reference files outside the staged diff |
| `sena-log-analyzer` | Stack frame file:line, issues-solved/INDEX.md signature match | "Pattern looks like" without signature match |
| `sena-researcher` | Context7 doc URL w/ section anchor | Cannot reject library based on stale training data alone |
| `sena-doc-writer` | Grounded file:line that exists | Cannot claim symbol exists without grep verification |
| `sena-code-reviewer` | Auto-block signature match | Gut-feel block — must escalate, not auto-reject |
| `sena-engineering-collaborator` | Past failure citation (issues-solved / lessons / archived plan) | Cannot add phases without explicit risk citation |

### 2. Feature implementation (all current + future AI features)

When designing any new feature that calls an LLM with retrieved context, structure it as:

```
output = combine(
    privileged_call(LLM, query, retrieved_context),    # teacher
    vanilla_call(LLM, query),                          # student
    gate_function(retrieval_quality, agreement),       # asymmetric trust
)
```

**Concrete SENA fits:**

| Feature | Privileged (teacher) | Vanilla (student) | Gate signal |
|---------|----------------------|-------------------|-------------|
| Case Review classify | Gemini Flash + pgvector past notes | Gemini Flash, no retrieval | pgvector cosine score; agreement → trust student, save retrieval cost |
| Case Review review (risk/anomaly flags) | Gemini Flash + history + audit log | Gemini Flash, current note only | Disagreement on flag → require BOTH to agree before surfacing to staff (reduces false positives) |
| Onboarding voice prompt | Full prompt + cross-screen bucket + state JSON | Just current step state | After 3 successful step transitions, drop cross-screen block (internalization) |
| Voice service Bedrock case note | Bedrock + prior shift context | Bedrock + just turn transcript | Disagreement on field → flag for staff review, don't auto-fill |
| Future feature: voice search / Q&A | LLM + RAG | LLM only | Retrieval similarity < threshold → attenuate teacher; ship student |

**Default for any new AI feature:** start with both teacher and student paths instrumented; ship gating logic once you have measurement.

### 3. The `/sena-learn` lessons loop (meta — already mostly applied)

Current rule: 3× occurrences → promote to CLAUDE.md.
SDAR upgrade: **weighted** occurrences, not raw count.

| Correction type | Weight |
|-----------------|--------|
| Explicit "no, wrong, stop" — high-confidence | 1.0 |
| Implicit reframe / re-ask — medium | 0.5 |
| Single user mood without recurrence | 0.2 |
| Self-induced (hook block, factual error) | 0.8 |

Promotion threshold: **weighted_sum ≥ 3.0**, not `Occurrences: 3+`. Prevents one emphatic user moment from over-promoting a one-off preference.

## When asymmetric trust does NOT apply

- **Hard constraints** (tenant isolation, NDIS APP 8/11, deprecated Gemini patterns, Pydantic v2, `assert_session_owner`) — these are deterministic. NO gating. Always reject.
- **Hook-enforced rules** (Write Guard, Context7 Gate, Gemini Skill Gate) — runtime-enforced, no agent-level override.
- **User explicit override** ("ignore lessons.md for this task") — user wins.
- **Single-source-of-truth artifacts** (current FormState in Redis, current git HEAD, current `pyproject.toml`) — these are not "retrieved context," they're ground truth.

## Recording use

When an agent applies this gate and rejects/accepts an output asymmetrically, the rationale ("teacher endorsed X, citation: file:line; teacher rejected Y, no anchor → attenuated") goes into the agent's response so the user can audit the gating logic.

## Harness verification

`sena-harness-upgrade` Phase 4 verifies this file exists and is referenced by `principal-engineer.md`. Phase 6 verifies no agent's `<principal_engineer_mode>` block contradicts the asymmetric-trust pattern.
