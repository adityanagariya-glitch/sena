"""Local test harness for the case-note monthly-summary APIs.

Edit the CONFIG block below (paste your JWT + ids), then run:

    /home/main/SENA/sena-ai/bin/python test.py            # interactive: choose org / mobile
    /home/main/SENA/sena-ai/bin/python test.py org         # test org_api   (port 8602)
    /home/main/SENA/sena-ai/bin/python test.py mobile      # test mobile_api (port 8603)

What it does:
  1. Picks the target app (org / mobile) from argv or an interactive prompt.
  2. If that app isn't already serving on its port, it launches it for you
     (python org_api.py / mobile_api.py) and waits for /health.
  3. Sends POST /casenote/monthly-summary with your JWT + body and prints the result.
  4. Shuts down only the server IT started (a server you launched yourself is left alone).

In production the JWT is supplied by the frontend (Flutter mobile / React web) in the
Authorization header — this script just simulates that caller locally.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

# ─────────────────────────── CONFIG — edit me ───────────────────────────
# Paste a JWT from your frontend / login here:
JWT_TOKEN = ""

# Request body:
ORGANIZATION_ID = ""
MEMBER_ID = ""
MONTH = 5          # 1-12
YEAR = 2026

# Optional convenience: if JWT_TOKEN is empty but these are set, the script logs
# in to get a token (and auto-fills ORGANIZATION_ID / MEMBER_ID if left blank).
LOGIN_EMAIL = ""
LOGIN_PASSWORD = ""
# ─────────────────────────────────────────────────────────────────────────

BACKEND = "https://dev-api.isena.org/api"
HERE = Path(__file__).resolve().parent
APPS = {
    "org":    {"file": "org_api.py",    "port": 8602},
    "mobile": {"file": "mobile_api.py", "port": 8603},
}
_BACKEND_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://dev-api.isena.org",
    "Referer": "https://dev-api.isena.org/",
}


def choose_app() -> str:
    if len(sys.argv) > 1 and sys.argv[1].lower() in APPS:
        return sys.argv[1].lower()
    while True:
        choice = input("Which API to test? [org / mobile]: ").strip().lower()
        if choice in APPS:
            return choice
        print("  please type 'org' or 'mobile'")


def login() -> tuple[str, str | None, str | None]:
    """Return (token, org_id, member_id) from /auth/ai/login."""
    print(f"[login] {LOGIN_EMAIL} …")
    try:
        resp = requests.post(
            f"{BACKEND}/auth/ai/login",
            json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
            headers=_BACKEND_HEADERS, timeout=20,
        )
    except requests.RequestException as e:
        sys.exit(f"[login] cannot reach backend: {e}")
    if resp.status_code != 200:
        sys.exit(f"[login] failed: HTTP {resp.status_code} — {resp.text[:200]}")
    data = resp.json().get("data", {})
    token = data.get("accessToken") or data.get("access_token") or data.get("token")
    membership = (data.get("user", {}).get("organizationMembership") or [{}])[0]
    org_id = (membership.get("organization") or {}).get("id") or \
        (data.get("defaultContext") or {}).get("organizationId")
    member_id = membership.get("id")
    print(f"[login] ok — org={org_id} member={member_id}")
    return token, org_id, member_id


def is_up(port: int) -> bool:
    try:
        return requests.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200
    except requests.RequestException:
        return False


def start_server(app: str) -> subprocess.Popen:
    """Launch the chosen app with the SAME interpreter running this script."""
    file = APPS[app]["file"]
    port = APPS[app]["port"]
    print(f"[server] starting {file} on :{port} …")
    proc = subprocess.Popen(
        [sys.executable, file], cwd=HERE,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):  # up to ~20s
        if is_up(port):
            print(f"[server] {file} is up")
            return proc
        if proc.poll() is not None:
            raise RuntimeError(f"{file} exited early (code {proc.returncode}) — run it directly to see the error")
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"{file} did not become healthy on :{port}")


def main() -> None:
    app = choose_app()
    port = APPS[app]["port"]

    token = JWT_TOKEN.strip()
    org_id, member_id = ORGANIZATION_ID, MEMBER_ID
    if not token and LOGIN_EMAIL and LOGIN_PASSWORD:
        token, lo, lm = login()
        org_id = org_id or lo
        member_id = member_id or lm
    if not token:
        sys.exit("No JWT. Paste one into JWT_TOKEN, or set LOGIN_EMAIL/LOGIN_PASSWORD.")

    started = None
    if not is_up(port):
        started = start_server(app)
    else:
        print(f"[server] {app} already running on :{port} — using it")

    try:
        body = {"organizationId": org_id, "memberId": member_id, "month": MONTH, "year": YEAR}
        print(f"\n[request] POST :{port}/casenote/monthly-summary")
        print(f"[request] body = {json.dumps(body)}")
        try:
            resp = requests.post(
                f"http://127.0.0.1:{port}/casenote/monthly-summary",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body, timeout=120,
            )
        except requests.RequestException as e:
            print(f"[request] failed to reach the API: {e}")
            return
        print(f"\n[response] HTTP {resp.status_code}\n")
        try:
            data = resp.json()
        except ValueError:
            print(resp.text)
            return
        # Print the summary readably, then the rest of the envelope.
        summary = data.pop("summary", None)
        print(json.dumps(data, indent=2))
        if summary is not None:
            print("\n──────── summary ────────\n")
            print(summary)
    finally:
        if started is not None:
            print(f"\n[server] stopping {APPS[app]['file']} (started by this script)")
            started.terminate()
            try:
                started.wait(timeout=5)
            except subprocess.TimeoutExpired:
                started.kill()


if __name__ == "__main__":
    main()
