# What changed on `ai-services` since the voice-assistant merge

**For:** anyone who last pulled around the `onboarding_casenote` / voice-assistance import and hasn't pulled since.
**Baseline:** `6e5a20b` — *"feat(restrictive-practices): import case-note voice assistant + NDIS analysis service"* (the voice import merge).
**Now:** `499b23a` on `origin/ai-services`.
**Scale:** 193 files changed (+4,082 / −20,052). ⚠️ The big deletion count is mostly **cleanup, not lost features** — see §4.

> TL;DR for the Flutter dev: the headline change is **voice dictation for the staff case-note screen** is now built backend-side. Your integration guide is **`services/case_review/FLUTTER_HANDOFF_VOICE.md`** — start there.

---

## 1. ⭐ NEW: Voice case-note dictation in `case_review` (the headline)

A Gemini Live voice assistant that lets a support worker **dictate the 7-section staff case note by voice** — built into `services/case_review`.

- **Endpoints:** `POST /v1/case-review/voice/session` (staff-gated, tenant-scoped) + `WSS /ws/case-review/voice/{session_id}`.
- **Model:** mobile-proxy / Option-D — your Flutter app stays the source of truth for the form; the server sends `tool_request`, you apply + echo back fresh state. Never auto-submits.
- **Schema:** matches the existing Flutter `CreateCaseNotePayload` exactly (all 7 sections, 17 required fields, validation 5–1000 / mood+injuryDetails 5–500, conditional `injuryDetails`, ≥1-document gate).
- **👉 Integration guide (read this):** `services/case_review/FLUTTER_HANDOFF_VOICE.md` — full WS/REST contract, the `section.field → CaseNoteFormController` map, and the **5 onboarding mistakes to NOT repeat** (mic-mute for echo, echo fresh state, handle every event, document gate, no auto-submit).

**What you (frontend) need to do:** wire a "Dictate" button on `case_note_form_screen.dart` to a new voice controller that drives the existing `CaseNoteFormController`. Everything you need is in the handoff doc.

**Backend internals (FYI, not your concern):** the Gemini Live engine was extracted out of `onboarding` into a shared library `sena_common.voice` so onboarding + case_review share one copy. Onboarding's behaviour is unchanged (its full test suite stayed green throughout). A dedicated Redis (`SENA_AI_CASE_REVIEW_REDIS_URL`, port 6380) was added for case_review voice session state.

---

## 2. Other new backend services (from the rest of the team)

These landed on `ai-services` in the same window. Flagged because some change API surfaces:

| Change | Notes for frontend |
|--------|--------------------|
| **`ai_chatbot` endpoints now use `/ai-chatbot` prefix** | If you call the chatbot gateway, **update the path prefix.** (commit `2b4c15d`) |
| **New `shift-summary` service** + consolidation API | New backend service (`services/shift-summary`) — shift-summary consolidation endpoint. (`0564283`, `863c683`) |
| **New `ai-communication-log` service** | New service scaffold `services/ai-communication-log`. (`0c2946f`) |
| **`policy_proc` + `staff` services** wired with Docker/Nginx + port mappings | New service routing; check with backend if you consume these. (`09ce2b1`, `be973d7`) |
| **`casenote_monthly`** restructured for client-activity-data retrieval API | If you consume monthly case-note data, the API shape changed. (`5714417`) |
| **OpenAPI specs** for staff/client APIs refactored | `openapi-specs/` updated — re-generate clients if you do. (`a399acc`) |

---

## 3. Infra / config

- `docker-compose.yml` / `.deploy.yml`: new port mappings (policy, staff, **case-review-redis @6380**), internal container naming.
- `services/nginx/`: reverse-proxy config for `dev-api.isena.org`.
- `services/Dockerfile`: build adjustments.
- `requirements.txt`: dependency cleanup across services.

---

## 4. ⚠️ Cleanup that looks scary in the diff but isn't a feature loss

The `−20,052` lines are dominated by **removals that are intentional cleanup**, NOT functionality:

- **`restrictive_practices/` untracked** (`983702a`) — that top-level folder was a *reference copy* pushed by mistake; it was removed from git and gitignored. The voice logic it contained now lives properly inside `services/` (extracted + reused). Nothing the app depends on was lost.
- **`index.py` (1,565 lines) removed** — obsolete root file.
- Misc obsolete JSON/trends files removed.

If you had `restrictive_practices/` locally from an earlier pull, it's now gitignored — you can delete your local copy; it's not part of the app.

---

## 5. How to catch up

```bash
git checkout ai-services
git pull origin ai-services      # fast-forward to 499b23a
```
Then, for the voice feature: open `services/case_review/FLUTTER_HANDOFF_VOICE.md`.

**If you have local uncommitted work**, stash or commit first — the pull touches docker-compose, nginx, and several `services/` dirs (but **not** `lib/` — no Flutter source changed on this backend repo).

---

## Appendix — commits since baseline (no merges)

```
Voice case-note dictation (this feature):
  b3ec84f refactor(voice): extract Gemini Live engine to shared sena_common.voice
  5d5c846 refactor(voice): parameterize FormStateRepo Redis namespace (prefix + tenant scope)
  c013928 refactor(voice): inject VoiceEngineConfig - decouple engine from onboarding.core.settings
  341a2dd refactor(voice): inject usage_feature + function_decls (final engine seam)
  141f688 feat(case-review): add dedicated Redis + Live API settings for voice dictation
  47ec743 feat(case-review): author voice case-note StepSchema from Flutter contract
  7b637c8 chore(case-review): sync requirements.txt with new redis dep
  518aaf2 feat(voice): parameterize dispatcher known_tools/submit_tool + case-note tool decls
  9557a9c feat(voice): template_name param + author case-note prompt
  1ac8c49 feat(case-review): voice case-note WS route + session-create endpoint
  f3d1e52 fix(onboarding): tenant ownership guard on the voice WS route
  75a1989 feat(case-review): make case-note prompt + schema screen-complete
  f3a9d87 docs(case-review): Flutter integration handoff for voice case-note dictation

Other team changes:
  0c2946f chore: add initial files for ai-communication-log
  0564283 feat: add shift-summary consolidation API
  863c683 feat: implement shift-summary service with API integration and Docker support
  a399acc Refactor OpenAPI specifications for staff and client APIs
  9f13199 chore(requirements): clean up dependencies
  caad85d feat: update Docker and Nginx configs for internal container naming
  4d0ee61 feat: update Nginx ports in docker-compose for reverse proxy
  39027dd fix: handle BOM in example.json loading
  91bf0a1 feat: add test script for SENA AI Chatbot Gateway with Docker support
  983702a chore: untrack top-level restrictive_practices/ + gitignore it
  4ed63dd chore: update .gitignore; remove obsolete JSON file
  5714417 refactor: restructure casenote.json for client activity data retrieval API
  887f7a6 Implement code changes to enhance functionality and improve performance
  09ce2b1 feat: add policy and staff services with Docker and Nginx configuration
  2b4c15d feat: update API endpoints to use /ai-chatbot prefix
  be973d7 feat: add port mappings for policy and staff services in docker-compose
```
