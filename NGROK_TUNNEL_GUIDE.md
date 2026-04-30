# Ngrok Tunnel Guide — Onboarding Service for Mobile Build

> **Purpose:** Expose the locally-running onboarding service (port 8083) so a physical phone or external mobile build can hit REST + WebSocket endpoints without being on the dev LAN.

**Service hosted:** `SENA_AI/sena-ai/services/onboarding/` (FastAPI + WSS, port 8083)
**Companion docs:** [`HANDOFF_VOICE_ONBOARDING.md`](HANDOFF_VOICE_ONBOARDING.md), [`FLUTTER_VOICE_INTEGRATION.md`](FLUTTER_VOICE_INTEGRATION.md)

---

## TL;DR

```bash
# Terminal 1 — backend listens on all interfaces
cd SENA_AI/sena-ai/services/onboarding
uvicorn src.onboarding.main:create_app --factory --reload --host 0.0.0.0 --port 8083 --forwarded-allow-ips='*' --proxy-headers

# Terminal 2 — tunnel
ngrok http 8083
```

ngrok prints `https://<sub>.ngrok-free.app -> http://localhost:8083`. Hand that base URL to the Flutter dev.

---

## 1. Install ngrok

| OS | Command |
|----|---------|
| Windows | `winget install ngrok.ngrok` or `scoop install ngrok` |
| macOS | `brew install ngrok/ngrok/ngrok` |
| Linux | `snap install ngrok` |

Verify: `ngrok version` → `3.x.x`.

---

## 2. Authenticate (one-time)

1. Sign up free at <https://dashboard.ngrok.com/signup>
2. Copy your authtoken from <https://dashboard.ngrok.com/get-started/your-authtoken>
3. Bind it locally:
   ```bash
   ngrok config add-authtoken <YOUR_TOKEN>
   ```

Token is written to `~/.ngrok2/ngrok.yml` (Linux/macOS) or `%HOMEPATH%\AppData\Local\ngrok\ngrok.yml` (Windows). Do **not** commit it.

---

## 3. Run the backend (must bind to 0.0.0.0)

```bash
cd SENA_AI/sena-ai/services/onboarding
pip install -e .   # if first run
uvicorn src.onboarding.main:create_app \
  --factory \
  --reload \
  --host 0.0.0.0 \
  --port 8083 \
  --forwarded-allow-ips='*' \
  --proxy-headers
```

Why each flag:
- `--host 0.0.0.0` — accept connections from any interface (ngrok forwards from outside `localhost`).
- `--forwarded-allow-ips='*'` + `--proxy-headers` — trust `X-Forwarded-Proto`/`X-Forwarded-For` from ngrok, so FastAPI builds `https://`/`wss://` URLs in OpenAPI + redirects.

---

## 4. Open the tunnel

```bash
ngrok http 8083
```

You will see:

```
Session Status         online
Account                you@example.com (Plan: Free)
Forwarding             https://abc123.ngrok-free.app -> http://localhost:8083
Connections            ttl     opn     rt1     rt5     p50     p90
                       0       0       0.00    0.00    0.00    0.00
```

The forwarding URL is your tunnel base. Replace `abc123` below with whatever you got.

---

## 5. URLs the mobile build uses

| Purpose | URL |
|---------|-----|
| REST — create session | `POST https://abc123.ngrok-free.app/v1/onboarding/session` |
| REST — read state | `GET https://abc123.ngrok-free.app/v1/onboarding/session/{id}/state` |
| REST — write state | `PUT https://abc123.ngrok-free.app/v1/onboarding/session/{id}/state` |
| REST — complete | `POST https://abc123.ngrok-free.app/v1/onboarding/session/{id}/complete` |
| WS — voice stream | `wss://abc123.ngrok-free.app/ws/onboarding/{session_id}` |
| Browser harness | `https://abc123.ngrok-free.app/harness` |
| OpenAPI docs | `https://abc123.ngrok-free.app/docs` |

> One tunnel covers **both** HTTPS and WSS. The WebSocket upgrade is a plain HTTP `Upgrade: websocket` header — ngrok forwards it transparently. Do **not** open a separate `ngrok tcp` tunnel.

---

## 6. The browser-warning gotcha (read this)

ngrok's free tier injects an HTML interstitial on first request from any non-browser user-agent. A mobile HTTP client receives a `200 OK` with an HTML body instead of your JSON, and the JSON parser explodes with an unhelpful error.

**Fix:** every request from the mobile app must include the bypass header.

### REST (Dio / http)

```dart
final dio = Dio(BaseOptions(
  baseUrl: 'https://abc123.ngrok-free.app',
  headers: {
    'ngrok-skip-browser-warning': 'true',
  },
));
```

### WebSocket (web_socket_channel)

```dart
final channel = WebSocketChannel.connect(
  Uri.parse('wss://abc123.ngrok-free.app/ws/onboarding/$sessionId'),
  // headers param available on IOWebSocketChannel only:
);

// On mobile (dart:io path), use IOWebSocketChannel.connect to inject headers:
final channel = IOWebSocketChannel.connect(
  'wss://abc123.ngrok-free.app/ws/onboarding/$sessionId',
  headers: {'ngrok-skip-browser-warning': 'true'},
);
```

---

## 7. Flutter wiring slot

The mobile app already has an `AppStrings.apiBaseUrl` constant. For tunnel mode the engineer can either:

1. **Hot-swap a constant** (fastest):
   ```dart
   class OnboardingEnv {
     static const String httpBase = 'https://abc123.ngrok-free.app';
     static const String wsBase   = 'wss://abc123.ngrok-free.app';
   }
   ```

2. **Use `--dart-define` at build time** (cleaner, no commits):
   ```bash
   flutter run \
     --dart-define=ONBOARDING_HTTP_BASE=https://abc123.ngrok-free.app \
     --dart-define=ONBOARDING_WS_BASE=wss://abc123.ngrok-free.app
   ```
   ```dart
   const httpBase = String.fromEnvironment('ONBOARDING_HTTP_BASE');
   const wsBase   = String.fromEnvironment('ONBOARDING_WS_BASE');
   ```

When the tunnel restarts and the subdomain rotates, only the constant or the `--dart-define` value needs to change — no code edit.

---

## 8. Static domain (skip the rotating subdomain)

Free tier gives **one** reserved static domain per account.

1. Visit <https://dashboard.ngrok.com/cloud-edge/domains>
2. Click "New Domain" → e.g. `sena-onboarding.ngrok-free.app`
3. Run with the static URL flag:
   ```bash
   ngrok http --url=sena-onboarding.ngrok-free.app 8083
   ```

Now the Flutter constant never changes between sessions.

---

## 9. Common failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Connection refused` on tunnel URL | Backend listening on `127.0.0.1` not `0.0.0.0` | Add `--host 0.0.0.0` |
| Mobile gets HTML instead of JSON | ngrok browser warning | Add header `ngrok-skip-browser-warning: true` |
| WS handshake 400 / 502 | App backend behind another proxy that strips upgrade headers | Run uvicorn directly (not through Caddy/nginx) for tunnel mode |
| OpenAPI shows `http://localhost:8083` instead of `https://...ngrok...` | uvicorn missing proxy flags | Add `--forwarded-allow-ips='*' --proxy-headers` |
| Tunnel disconnects after 2h | Free tier session cap | Restart `ngrok http 8083` |
| `ERR_NGROK_3200` / 429 | Too many connections / abused | Wait, or upgrade plan |

---

## 10. Security note (read before sharing the URL)

A live ngrok tunnel makes your laptop publicly reachable. Until JWT auth is wired (it is **not** yet — `dev_header` mode only), anyone with the URL can:

- Create onboarding sessions
- Open WS streams (and consume your Gemini Live quota)
- Read/write FormState

**Mitigations while testing:**
- Stop `ngrok` when not actively testing (`Ctrl+C`).
- Add ngrok basic-auth in front of the tunnel:
  ```bash
  ngrok http 8083 --basic-auth='sena:secret'
  ```
  Then mobile sends `Authorization: Basic c2VuYTpzZWNyZXQ=` on every request.
- Do **not** post the tunnel URL in a public chat / GitHub issue.

When JWT auth lands (pluggable seam in `core/settings.py`), this mitigation can drop.

---

## 11. Quick smoke test (no Flutter needed)

```bash
# REST — create a session against the tunnel
curl -X POST https://abc123.ngrok-free.app/v1/onboarding/session \
  -H 'Content-Type: application/json' \
  -H 'ngrok-skip-browser-warning: true' \
  -H 'X-User-Id: dev-user' \
  -H 'X-User-Roles: client' \
  -d @sena-ai/services/onboarding/fixtures/schema_personal_information.json

# Open browser harness — visit:
https://abc123.ngrok-free.app/harness?ngrok-skip-browser-warning=true
```

If `/harness` loads and lets you connect a WS, the tunnel is wired correctly.

---

## 12. Stopping cleanly

- `Ctrl+C` in the ngrok terminal — closes tunnel, drops in-flight WS connections.
- `Ctrl+C` in the uvicorn terminal — same.
- Order does not matter; ngrok will report `Connections: 0` and exit when uvicorn dies first.
