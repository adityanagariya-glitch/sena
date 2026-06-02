#!/usr/bin/env python
"""SENA unified router test — ONE terminal, one process.

What it does:
  1. Spawns the two backends and streams their logs here, prefixed:
        [staff]   → services/staff/api_main.py     (port 8601)
        [policy]  → services/policy_proc/app/main.py (port 8000)
  2. Logs you in to BOTH auth systems:
        staff   → real ISENA API (email + password)
        policy  → policy_proc /auth/login (fake_users.json test account)
  3. REPL: type a question. It is classified by Bedrock and routed:
        user q : <your question>
        api    : staff | policy_proc | out of scope
     then that folder's live logs appear, followed by the answer.
  4. On exit ('quit', 'exit', or Ctrl+C): terminates both backends and
     frees all ports (8601, 8000, 9000).

Run:
    cd /home/main/SENA/services/ai_chatbot
    python run.py
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time

import httpx

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
STAFF_DIR = os.path.join(REPO_ROOT, "services", "staff")
POLICY_DIR = os.path.join(REPO_ROOT, "services", "policy_proc")

STAFF_PORT = 8601
POLICY_PORT = 8000
PORTS = [STAFF_PORT, POLICY_PORT, 9000]

STAFF_URL = f"http://127.0.0.1:{STAFF_PORT}"
POLICY_URL = f"http://127.0.0.1:{POLICY_PORT}"

# Default policy test account (from fake_users.json). Override at the prompt.
POLICY_LOGIN_ID = "sunrise\\alice.walker"
POLICY_PASSWORD = "Test@1234"

import auth                      # ISENA login (staff)
from router import route_query   # Bedrock classification

_children = []
_staff_token = None
_policy_token = None


# ── colours ───────────────────────────────────────────────────────────────────
def c(text, code):
    return f"\033[{code}m{text}\033[0m"

BOLD, DIM, GREEN, CYAN, YELLOW, RED, MAGENTA = "1", "2", "32", "36", "33", "31", "35"


# ── child process management ────────────────────────────────────────────────────
def _pump(name, proc, colour):
    prefix = c(f"[{name}]", colour)
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode(errors="replace").rstrip("\n")
        print(f"{prefix} {line}", flush=True)


def _spawn(name, argv, cwd, colour):
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": REPO_ROOT}
    proc = subprocess.Popen(
        argv, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    t = threading.Thread(target=_pump, args=(name, proc, colour), daemon=True)
    t.start()
    _children.append((name, proc))
    return proc


def _wait_health(url, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=2).status_code < 400:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _free_ports():
    print(c("\n[run] freeing ports " + ", ".join(map(str, PORTS)) + " ...", YELLOW))
    for name, proc in _children:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
    for _, proc in _children:
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    # Belt-and-braces: kill anything still holding the ports.
    for port in PORTS:
        subprocess.run(
            f"lsof -ti:{port} | xargs -r kill -9",
            shell=True, capture_output=True,
        )
    print(c("[run] ports closed. bye.", YELLOW))


# ── auth ────────────────────────────────────────────────────────────────────────
def _login_staff():
    global _staff_token
    print(c("\n— Staff login (real ISENA API) —", BOLD))
    email = input("  email: ").strip()
    password = input("  password: ").strip()
    if auth.login_user(email, password):
        _staff_token = auth.get_token()
        print(c("  ✓ staff authenticated", GREEN))
        return True
    print(c(f"  ✗ staff login failed: {auth.get_last_error()}", RED))
    return False


def _login_policy():
    global _policy_token
    print(c("\n— Policy login (policy_proc test account) —", BOLD))
    login_id = input(f"  login_id [{POLICY_LOGIN_ID}]: ").strip() or POLICY_LOGIN_ID
    password = input(f"  password [{POLICY_PASSWORD}]: ").strip() or POLICY_PASSWORD
    try:
        r = httpx.post(
            f"{POLICY_URL}/auth/login",
            json={"login_id": login_id, "password": password},
            timeout=10,
        )
        if r.status_code == 200:
            _policy_token = r.json()["token"]
            print(c("  ✓ policy authenticated", GREEN))
            return True
        print(c(f"  ✗ policy login failed: {r.status_code} {r.text}", RED))
    except Exception as e:
        print(c(f"  ✗ policy login error: {e}", RED))
    return False


# ── calling a backend and streaming its SSE answer ──────────────────────────────
def _call(url, token, question):
    answer, blocked = [], None
    payload = {"question": question, "is_new_chat": True}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        with httpx.stream("POST", f"{url}/query/stream", json=payload,
                          headers=headers, timeout=120) as resp:
            if resp.status_code != 200:
                return f"(error {resp.status_code}: {resp.read().decode(errors='replace')})"
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    line, buf = buf.split("\n\n", 1)
                    if not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    t = ev.get("type")
                    if t == "token":
                        answer.append(ev.get("text", ""))
                    elif t == "blocked":
                        blocked = ev.get("text", "(blocked)")
                    elif t == "error":
                        answer.append(f"\n⚠️ {ev.get('text', 'error')}")
    except Exception as e:
        return f"(call failed: {type(e).__name__}: {e})"
    if blocked:
        return f"[blocked] {blocked}"
    return "".join(answer).strip() or "(no response)"


# ── one question → classify → route → answer ────────────────────────────────────
def handle(question):
    print(c("\nuser q : ", CYAN) + question)
    routing = asyncio.run(route_query(question, {}))
    targets = routing["target_services"]
    cls = routing["classification"]

    if not targets:
        print(c("api    : ", CYAN) + c("out of scope", MAGENTA) +
              c(f"  ({cls.get('reason', '')})", DIM))
        print(c("\nanswer : ", GREEN) +
              "This question is out of scope — I can only help with staff or policy questions.")
        return

    label = " + ".join("policy_proc" if t == "policy" else t for t in targets)
    print(c("api    : ", CYAN) + c(label, YELLOW) +
          c(f"  ({cls.get('confidence', 0):.0%} — {cls.get('reason', '')})", DIM))

    for t in targets:
        if t == "staff":
            print(c("\n--- staff logs ---", DIM))
            ans = _call(STAFF_URL, _staff_token, question)
        else:
            print(c("\n--- policy_proc logs ---", DIM))
            ans = _call(POLICY_URL, _policy_token, question)
        tag = "policy_proc" if t == "policy" else t
        print(c(f"\nanswer ({tag}) :\n", GREEN) + ans)


def main():
    print(c("=== SENA unified router test ===", BOLD))
    print("Starting backends (logs stream below)...\n")

    _spawn("staff", [sys.executable, "-m", "uvicorn", "api_main:app",
                     "--host", "127.0.0.1", "--port", str(STAFF_PORT)],
           STAFF_DIR, CYAN)
    _spawn("policy", [sys.executable, "-m", "uvicorn", "app.main:app",
                      "--host", "127.0.0.1", "--port", str(POLICY_PORT)],
           POLICY_DIR, MAGENTA)

    print(c("\n[run] waiting for staff ...", YELLOW))
    staff_ok = _wait_health(STAFF_URL)
    print(c(f"[run] staff {'ready' if staff_ok else 'TIMEOUT'}", GREEN if staff_ok else RED))
    print(c("[run] waiting for policy ...", YELLOW))
    policy_ok = _wait_health(POLICY_URL)
    print(c(f"[run] policy {'ready' if policy_ok else 'TIMEOUT'}", GREEN if policy_ok else RED))

    _login_staff()
    _login_policy()

    print(c("\n=== Ask away (type 'quit' to exit) ===", BOLD))
    while True:
        try:
            q = input(c("\n> ", BOLD)).strip()
        except EOFError:
            break
        if not q:
            continue
        if q.lower() in ("quit", "exit", "q"):
            break
        handle(q)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        _free_ports()
