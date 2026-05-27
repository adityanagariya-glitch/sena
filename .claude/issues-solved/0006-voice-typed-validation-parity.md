---
id: 0006
symptom: "Voice writes bypass frontend validators; validation_rejection events silently dropped; no input_method tracking"
aliases:
  - "voice fills bad data into Step 1 form"
  - "typed errors not reported back to agent"
  - "validation_rejection event ignored by Flutter"
  - "voice rejection has no audio feedback"
  - "cross-field invariant only enforced at advance gate"
  - "emergency contact phone equals client phone but Sena accepted it"
root_cause: "Voice sink wrote raw STT directly to controllers, bypassing the typed-input validator pipeline; `validation_rejection` WS event had no consumer; backend had no /errors endpoint for typed-side reporting; `input_method` was never threaded through, so audits couldn't tell which channel rejected."
tags: [onboarding, voice, validation, flutter, contract]
files:
  - SENA_AI/flutterhandoffdev.md
  - sena-ai/services/onboarding/src/onboarding/api/routes.py
  - sena-ai/services/onboarding/src/onboarding/models/form_state.py
  - sena-ai/services/onboarding/src/onboarding/services/field_apply.py
  - sena-ai/services/onboarding/src/onboarding/services/tools.py
  - sena-ai/services/onboarding/src/onboarding/services/validators/field_rules.py
  - sena-ai/services/onboarding/src/onboarding/services/validators/cross_field.py
  - sena-ai/services/onboarding/tests/test_errors_endpoint.py
  - sena-ai/services/onboarding/tests/test_field_apply.py
  - sena-ai/services/onboarding/tests/test_validators.py
fix_commit: ""
date_solved: 2026-05-12
verified: "6-agent orchestration (auditor→mapper→handoff→backend→docs→QA); backend test suite green; frontend impl pending in sena-mobile per flutterhandoffdev.md"
---

# 0006 — Voice/typed validation parity (Step 1 client onboarding)

## Symptom

Three user-visible failure modes, all rooted in the same parity gap:

1. Voice could write any value to a Step-1 field — phone numbers in name fields, email
   typos, emergency-contact phone equal to the participant's own phone, plan-end before
   plan-start. None of the typed-input validators ran on voice writes.
2. When server-side validators **did** reject a voice write, the resulting
   `validation_rejection` WS event was dropped by Flutter (no `case` arm in
   `VoiceEventModel.parse`). The user got no error, the mic did not re-open, the agent
   often plowed ahead.
3. Typed validation failures stayed entirely client-side — the agent had no way to learn
   "the user just failed email validation 3 times in a row" because there was no
   `POST /errors` endpoint.

Audit trail also could not tell which input method had produced a value — `FieldValue` had
no `input_method` discriminator.

## Root cause

Two parallel input pipelines (voice sink + typed forms) evolved without a shared
validation contract:

- **Voice sink:** raw STT result → directly to GetX controllers → backend `update_field`.
  The frontend validator chain (the same code typed forms use on every keystroke) was
  never invoked.
- **Typed forms:** validators ran inline, but failures stayed in Flutter — no telemetry,
  no agent feedback.
- **`validation_rejection` WS event:** backend emitted it, Flutter consumer ignored it.
  The schema-drift work in Task #14 (Issue #18) was specced but not implemented.
- **Cross-field invariants** (emergency-contact phone ≠ client phone; plan end > plan
  start) only ran at the `advance_step` gate — too late to give the user feedback at the
  point of the bad write.

## Fix (6-agent orchestration, 2026-05-12)

Backend wired end-to-end; frontend contract written; frontend implementation pending in
the `sena-mobile` Flutter repo per `SENA_AI/flutterhandoffdev.md`.

**Canonical Flutter contract:** `SENA_AI/flutterhandoffdev.md` (1651 lines, 91.8 KB, as of
2026-05-12 QA pass). Specifies per-field validators, voice-sink interception,
`validation_rejection` parsing, TTS error-speak + mic auto-reopen, AppStrings additions
(including paired on-screen / `voice*` keys for fields whose spoken text differs from the
inline error), the full Step-1 field map.

**Backend changes in `sena-ai/services/onboarding/`:**

```diff
+ # New endpoint
+ POST /v1/onboarding/session/{session_id}/errors
+   → 204; strict body shape; persists to Redis list
+   → sena:onboarding:errors:{sid}  (7-day TTL)

+ class FieldValue:
+     input_method: Literal["typed", "voice"] | None

+ # build_envelope() now surfaces input_method on every field_apply event

+ # _update_field now runs the cross-field invariant check per-write
+ # (no longer only at advance gate)

+ # Reconciled cross-field reason_human strings to match Flutter AppStrings
+ # verbatim (emergency-contact phone-equals-client, duplicate-contact,
+ # plan-end-before-start)

+ basics.interpreter_required → _v_boolean_required
+ basics.about_me            → _v_text250_required
```

New tests: `test_errors_endpoint.py`, `test_field_apply.py`; extended
`test_validators.py`.

**The 5 non-negotiable contract rules (also in `.claude/SESSION_START.md`):**

1. Field never updates before validation passes — typed **or** voice.
2. `input_method` ("typed"|"voice") captured at intake, threaded through every
   validator + error report.
3. POST `/v1/onboarding/session/{session_id}/errors` on every validation FAIL.
4. Voice failure → TTS speaks the same on-screen string + auto-reopens mic.
5. Voice = first-class. Every rule applies equally to both input methods.

## Failed attempts (do NOT retry)

- **"Just add another `case` arm in `VoiceEventModel.parse`"** — was the original Issue
  #18 plan. Insufficient: parsing the event without a validate-before-state pipeline
  still lets voice write bad data; the rejection arrives after the controller already
  updated.
- **"Re-run validators on `field_apply` at the Flutter end"** — too late. By the time
  `field_apply` reaches the controller, the value has been broadcast to other widgets
  observing the same field; reverting is racy and visually flickery.
- **"Run cross-field invariants only at `advance_step`"** — the pre-2026-05-12 behaviour.
  Gives no in-context feedback; user has filled 8 fields before learning field 2 was
  invalid against field 5.
- **"Add `POST /errors` but skip the `input_method` field"** — fails the audit
  requirement: we can't distinguish which channel rejected, so we can't tune the voice
  prompt vs. typed validator copy independently.

## Why this fix (not alternatives)

The parity gap was a contract problem, not a code problem. Patching either side alone
would have drifted again within one sprint (the Task #14 / Issue #18 plan proved that —
spec without contract → silent regression). `SENA_AI/flutterhandoffdev.md` is the durable
fix: a single document the Flutter team and backend team both reference, with the 5 rules
encoded as test fixtures on both sides. Future field additions update the handoff doc
first, then both implementations follow.

## Related

- Task: `.claude/tasks/TASKS.md` #17
- Contract: `SENA_AI/flutterhandoffdev.md`
- Session-start protocol: `.claude/SESSION_START.md` § "Voice-Onboarding Validation
  Contract (added 2026-05-12)"
- Predecessor (Flutter consumer gaps): Task #14 Issues #18-#22 in `flutterhandoffdev.md`
- State-sync siblings: Task #13 (validation awareness), Task #15 (state-sync desync)
