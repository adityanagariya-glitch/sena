# Onboarding Voice — Local Testing & Frontend Checklist

Written after debugging the **"Voice unavailable: status code 503"** error (2026-06-12).

## TL;DR — what the 503 actually was

`Voice unavailable: ... status code 503` is **NOT a frontend bug and NOT new code**. It comes from one place in the backend: onboarding pings Redis on session-create (`api/routes.py:571`); if that ping fails it raises `503 "Redis unavailable"`, which the Flutter app shows as "Voice unavailable."

**Root cause:** onboarding's `.env` sets `SENA_AI_REDIS_URL` to a **cloud Upstash Redis** (`…upstash.io`). Upstash free DBs go cold/idle, so the ping timed out → 503. Your **local** Redis (`localhost:6379`) was up the whole time but wasn't being used.

**Fix for local testing:** point onboarding at local Redis (`redis://localhost:6379`). Then the ping is instant + reliable.

> Nothing in the WS contract, events, ports, or message shapes changed during the case_review work. The onboarding voice client needs **no code changes** — this was purely a backend env/Redis config issue.

---

## A. Running the backend locally (what we were testing)

Run onboarding from **its own folder + its own venv**, with the local-Redis override. Paste each line separately (don't let PowerShell wrap to `>>`):

```powershell
cd "C:\Users\Admin\Desktop\SENA_NEW\sena-mobile\SENA\services\onboarding"
$env:SENA_AI_REDIS_URL = "redis://localhost:6379"
& "C:\Users\Admin\Desktop\SENA_NEW\sena-mobile\SENA\services\onboarding\.venv\Scripts\python.exe" -m uvicorn onboarding.main:create_app --factory --host 0.0.0.0 --port 8083
```

**Success looks like:**
```
INFO:     Uvicorn running on http://0.0.0.0:8083 (Press CTRL+C to quit)
INFO:     Application startup complete.
```
No "Redis not reachable", no traceback.

**Gotchas that bit us:**
- Run from `services\onboarding` (not `case_review`) — wrong dir → `ModuleNotFoundError: No module named 'src.onboarding'`. Using `onboarding.main` (installed package) avoids this.
- Use onboarding's venv (`services\onboarding\.venv`), not the root `.venv` — different package set.
- `$env:SENA_AI_REDIS_URL` lasts only for that terminal session. To make it permanent, add `SENA_AI_REDIS_URL=redis://localhost:6379` to `services/onboarding/.env`.
- `--host 0.0.0.0` so a phone/emulator can reach it (not just `127.0.0.1`).

**To make the fix permanent (optional):** create/edit `services/onboarding/.env` (the local file overrides the shared root `.env`) with:
```
SENA_AI_REDIS_URL=redis://localhost:6379
```

---

## B. Frontend dev checklist (onboarding voice — client & staff)

### 1. Point the app at the running backend (the #1 cause of "can't connect" / reset)
| Where the app runs | Base host to use |
|--------------------|------------------|
| Android **emulator** | `http://10.0.2.2:8083` (10.0.2.2 = the host PC's localhost) |
| iOS **simulator** | `http://localhost:8083` |
| **Physical phone** (same Wi-Fi) | `http://<PC-LAN-IP>:8083` (e.g. `192.168.x.x`) |
| via **ngrok** tunnel | `https://<sub>.ngrok-free.dev` → forwards to `:8083` |

`localhost` on a physical device points at the **phone**, not your PC — that's why it fails.

### 2. Endpoints / ports
- REST session create: `POST http://<host>:8083/v1/onboarding/session`
- WebSocket voice: `ws(s)://<host>:8083/ws/onboarding/{session_id}`
- Health: `GET http://<host>:8083/health`
- (Behind nginx on a server, these live under `/onboarding/…` instead — but for **local** it's direct `:8083`.)

### 3. If you see `503 "Voice unavailable"`
That's the **backend** telling you a dependency (Redis) is down — **not** a frontend bug. Action:
- Check the **server terminal**: a "Redis not reachable" line = the backend env issue above (point it at local Redis).
- Retrying may temporarily work if it's the Upstash cold-start — but the real fix is local Redis.

### 4. If you see `Connection reset by peer` on the WS
- The backend isn't running, the host/port is wrong (see table 1), or (on a server) the nginx `/onboarding/` WebSocket-upgrade route. For **local**, it's almost always the wrong host/port.

### 5. No onboarding client changes needed
The WS events, `tool_request`/`tool_response` protocol, audio formats (PCM16 16 kHz in / 24 kHz out), and ports are unchanged from before the case_review work. Don't refactor the onboarding voice client for this.

---

## C. Note for case_review voice (separate feature)
case_review voice uses a **different** env var, `SENA_AI_CASE_REVIEW_REDIS_URL` → defaults to `redis://localhost:6380` (a *dedicated* Redis, not the 6379 one). It is **not running locally yet** — start a Redis on 6380 (or override that var to `:6379`) before testing case_review voice. See `services/case_review/FLUTTER_HANDOFF_VOICE.md` for that integration.

---

## Quick diagnostics
```powershell
# Is local Redis up? (prints True)
& "C:\Users\Admin\Desktop\SENA_NEW\sena-mobile\SENA\services\onboarding\.venv\Scripts\python.exe" -c "import redis; print(redis.from_url('redis://localhost:6379').ping())"

# Is the backend up + healthy?
curl http://localhost:8083/health
```
