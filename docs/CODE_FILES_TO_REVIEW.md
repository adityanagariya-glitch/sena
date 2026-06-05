# Code Files To Review — Dev-Only Routes & Demo Stack

Generated: 2026-05-14  
Context: Post-deployment cleanup. Voice assistance is live on EC2. These code files served
development purposes and may no longer be needed. Listed here for your review — NOT auto-deleted.

---

## 1. Harness routes in `main.py` (onboarding service)

**File:** `sena-ai/services/onboarding/src/onboarding/main.py`

**Lines:** 15, 40–59

```python
# Line 15
HARNESS_DIR = Path(__file__).resolve().parents[2]

# Lines 40–49 — serves test_harness.html (already deleted)
@app.get("/harness", include_in_schema=False)
async def serve_harness() -> FileResponse:
    p = HARNESS_DIR / "test_harness.html"
    if not p.exists():
        raise HTTPException(404, "test_harness.html not found")
    return FileResponse(p, media_type="text/html",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

# Lines 51–59 — serves fixture JSON files for the harness
@app.get("/harness/fixtures/{step_id}", include_in_schema=False)
async def serve_fixture(step_id: str) -> FileResponse:
    if not step_id.replace("_", "").isalnum():
        raise HTTPException(400, "invalid step_id")
    p = HARNESS_DIR / "fixtures" / f"schema_{step_id}.json"
    if not p.exists():
        raise HTTPException(404, f"fixture not found: {step_id}")
    return FileResponse(p, media_type="application/json")
```

**What it does:** Browser-accessible test harness for dev testing phases A/B/C.  
**Impact if removed:** `GET /harness` and `GET /harness/fixtures/{step_id}` return 404 (already
the case since `test_harness.html` was deleted). Safe to remove the routes + `HARNESS_DIR`
constant + `FileResponse` import (if unused elsewhere).  
**To remove:** Delete lines 15, 40–59 from `main.py`. Verify `FileResponse` still needed — it is
used for fixture serving so check if `HTTPException` is still needed too (yes — used in routes.py).

---

## 2. Demo stack (standalone Gemini Live demo)

**Files:**
- `sena-ai/demo_live_server.py` — FastAPI server bridging browser WebSocket ↔ Gemini Live
- `sena-ai/demo_client.html` — browser UI with mic capture + audio playback

**Referenced in:**
- `CLAUDE.md` "Demo Stack" section
- `SESSION_START.md` "Active services & ports" (port 8082)
- `TASKS.md` #1 (completed 2026-04-17 — original voice streaming proof-of-concept)

**What it does:** Standalone dev demo, NOT connected to the production onboarding service.  
**Impact if removed:** No production impact. Local dev loses the quick browser test page.  
**Decision:** Keep for local debugging? Or remove since onboarding service has its own test suite?

If you decide to remove: also update `CLAUDE.md` "Demo Stack" section, `SESSION_START.md`
"Active services" table, and the backlog item "Audio transcription display in demo UI" in TASKS.md.

---

## Status

- [ ] Harness routes in `main.py` — awaiting decision
- [ ] `demo_live_server.py` + `demo_client.html` — awaiting decision
