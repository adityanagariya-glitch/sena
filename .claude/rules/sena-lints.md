---
description: SENA Lint Checklist — single source of truth for the severity-labeled checks that /sena-approve, /sena-code-reviewer, sena-business-reviewer, sena-security-reviewer, and the harness Phase 4 all reference. Adapted from Reality-Check Senior _shared/lints.md (2026-05-26). Canonical always-loaded; agents inherit by `@-reference` from skills/agents.
---

# SENA Lint Checklist

Single source of truth. Every reviewer, every approve-gate, every harness audit checks against this file. When updating: change once here, all consumers pick it up.

## 🔴 Tenant isolation + NDIS compliance (BLOCKER — career-ending if shipped)

Every miss is a hard block. Treat as legal/regulatory failure, not a code smell.

- **Cross-tenant leak vector.** Any Redis key, Postgres row, Gemini prompt context, or webhook payload that doesn't include `tenant_id` in the lookup. Grep for `state_repo`, `user_context_repo` — every read/write must scope by tenant.
- **`assert_session_owner` missing.** Any route handler accepting `session_id` must call `assert_session_owner(session_id, current_user.tenant_id)` before any data access. No exceptions.
- **NDIS APP 8 / APP 11 violation.** Australian data crossing borders. Any external service call (LLM, webhook, third-party) must verify the endpoint is in `australia-southeast1` or equivalent. `GEMINI_REGION` env var must NOT be overridden to a non-AU region.
- **Auto-submit AI output.** No AI-generated case note, classification, or flag ships to the participant record without an explicit staff acknowledgement in the audit log. Auto-approve = blocker.
- **Audit log gap.** Any AI action (classify, summarise, review, flag) without a corresponding `ReviewAuditLog` entry. Every AI decision needs an audit row with timestamp + actor + decision.
- **Secret committed.** API key, JWT, AWS credentials, webhook secret in any file. Run `git secrets` or grep for `AKIA|sk-|ghp_|hf_`.

## 🔴 Deprecated Gemini patterns (BLOCKER — silent VAD death + wire mismatches)

- **Old API in `_browser_to_gemini` or any gemini*.py:** `session.send(input=..., end_of_turn=True)`, `LiveClientRealtimeInput(media_chunks=[...])`, `send_client_content(...)` for NEW messages (only valid for seeding initial history).
- **Deprecated model strings:** `gemini-2.5-flash-native-audio*`, `gemini-live-2.5-flash-preview`, `gemini-2.0-flash-live-001`. Current: `gemini-3.1-flash-live-preview` (Live) + `gemini-3-flash-preview` (Flash).
- **Mic gating on `_agent_speaking`:** server-side flag in `_browser_to_gemini` that stops forwarding audio while agent is speaking. Causes silent VAD death after 2-4 turns. Mic gating belongs in the Flutter client during `turn_start` → `turn_complete`, NOT the server.
- **`media=` key in `send_realtime_input`:** wrong — use specific keys `audio=` / `video=` / `text=`.

## 🟠 Python stack invariants (SERIOUS — breaks at cleaner gate)

- **Pydantic v1 patterns:** `.dict()`, `.parse_obj()`, `@validator`. Project is v2-only: use `model_dump()`, `model_validate()`, `@field_validator`.
- **Sync I/O on the event loop:** `requests.get(...)`, `time.sleep(...)`, blocking file I/O inside `async def`. All HTTP via `httpx.AsyncClient`; all waits via `asyncio.sleep`; all file ops via `aiofiles` if hot path.
- **`os.environ` direct reads:** must go through `core/settings.py` `pydantic-settings` model. No bare `os.getenv("SENA_AI_*")` outside that file.
- **`print()` / `breakpoint()` / `import pdb` in committed code.** Project uses `structlog`. Cleaner blocks these at commit time.
- **N+1 Redis calls:** sequential `await redis.get(key)` in a loop. Must pipeline with `async with redis.pipeline() as pipe`.
- **Sequential `await` in independent work:** Use `asyncio.gather(*[task() for ...])` instead of `for x in items: await task(x)` unless ordering matters.
- **Missing `tenant_id` in Redis key construction:** even if the route guard passed, key must include `tenant_id` as defense-in-depth.

## 🟠 LLM / RAG / Agent invariants (SERIOUS — accuracy + cost)

- **No verification of model output before user-facing action.** Any field auto-filled from Gemini turn transcript must have a corresponding validator (`field_rules`, `cross_field`) before being applied.
- **Asymmetric privileged trust violated.** If a feature uses retrieved context (RAG, cross-screen bucket, schema injection), it must structure as teacher (with retrieval) + student (without) + gate — see `.claude/rules/asymmetric-privileged-trust.md`. Symmetric trust is a SERIOUS finding when retrieval quality varies.
- **No retrieval-quality signal logged.** pgvector cosine score, recency, source must be logged when retrieval influences output. Without it, you can't tune the gate.
- **Prompt injection surface.** User-controlled strings (transcript, field values) interpolated into system prompts without sanitisation. Quote them, escape angle brackets, drop control characters.
- **Hardcoded prompt strings repeated across files.** Single source of truth in `services/prompts/` only.

## 🟠 Test + reproducibility (SERIOUS)

- **No test for new non-trivial function.** Per CLAUDE.md Hard Limits: every non-trivial function ships with a matching test in `services/<svc>/tests/`.
- **Test hits real Redis/Postgres instead of `fakeredis` / sqlite.** Slow + flaky + leaks across runs. Use the project's existing fixtures.
- **`@pytest.mark.asyncio` missing on async test.** `asyncio_mode = "auto"` is configured but the marker is still required by the project's pytest setup.
- **Missing fixture cleanup.** Test creates state in Redis/DB and doesn't tear down. Cross-test pollution.

## 🟡 Code quality (CONCERN — worth discussing while touching)

- **Function >100 lines or cyclomatic complexity >8** (ruff C901). Refactor signal.
- **Line >100 chars.** ruff enforced.
- **`Any` / `# type: ignore` / `# noqa` used to silence tooling.** Either fix the underlying issue or surface it with a `# TODO(#NNN)` referencing a real ticket.
- **Wrapped function call in try/except with empty handler.** Let errors propagate unless there's a real recovery path.
- **Comments restating WHAT the code does.** Comments explain WHY only.
- **`Rx<T?>` / `.value = newList`:** Flutter mobile only — use `Rxn<T>` / `assignAll(...)`. Caught by mobile reviewer.

## 🔵 Style (NIT — author may ignore)

- Australian-English spelling in user-facing copy (behaviour, organisation, centre).
- 24-hour time format / YYYY-MM-DD dates in logs.
- Module docstrings on public surfaces.
- Naming consistency with existing service patterns (validators, repositories, services).

## How to apply this

- **In `/sena-approve`:** any 🔴 → DENIED. Any 🟠 → DENIED. Only 🟡/🔵 → CONDITIONAL APPROVAL. Clean → APPROVED.
- **In `/sena-code-reviewer`:** the auto-block signatures table is the 🔴 + 🟠 rows from this file. Surface 🟡/🔵 as suggestions.
- **In `@agent-sena-business-reviewer`:** focus on 🔴 NDIS rows + the LLM/RAG block. FLAG only; hand back to bug-fixer.
- **In `@agent-sena-security-reviewer`:** focus on 🔴 tenant + secret + Gemini rows. Critical findings halt the workflow.
- **In `@agent-sena-cleaner`:** focus on 🟠 Python stack rows + 🟡 code quality. FIX inline.
- **In harness Phase 4:** verify this file exists. Phase 6 verifies it's not orphaned (at least one consumer must reference it).

## Updating

Treat like code: edit, commit. New lint discovered? Add a row. Lessons.md entry promoted to permanent rule? It probably lives here, not in CLAUDE.md. Severity bump? Justify in the commit message.
