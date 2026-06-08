# SENA Onboarding — Exact Dev Setup

## Uvicorn Command

Run from `SENA_AI/sena-ai/services/onboarding/` with `.venv` activated:

```powershell
C:\Users\Admin\Downloads\SENA\.venv\Scripts\Activate.ps1

uvicorn src.onboarding.main:create_app --factory --reload --host 0.0.0.0 --port 8089 --forwarded-allow-ips='*' --proxy-headers
```

## ngrok Command

In a separate terminal:

```powershell
ngrok http 8089 --log=stdout
```

ngrok authtoken already configured. Tunnel URL:

```
https://require-psychic-disprove.ngrok-free.dev  →  localhost:8089
```

## API Endpoint

```
POST https://require-psychic-disprove.ngrok-free.dev/v1/onboarding/session
Content-Type: application/json
ngrok-skip-browser-warning: true

{
  "participant_id": "e64ae455-eee5-4e19-9edc-88bcf846569d",
  "tenant_id":      "3f7279a3-7da0-45d6-9c8b-4a4bd3bd096a",
  "step":           "personal_information",
  "schema":         {}
}
```

## Health Check

```
GET http://127.0.0.1:8089/health/live
GET http://127.0.0.1:8089/docs
```

## Notes

- ngrok free-tier URL changes on every restart — update this file when it does.
- Uvicorn must be running BEFORE ngrok or ngrok returns `ERR_NGROK_8012`.
- `ngrok-skip-browser-warning: true` header required for non-browser clients.
