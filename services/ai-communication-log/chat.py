"""
Interactive conversation tester for the Sena classifier.

Simulates the Sena backend debounce logic:
  - Batch trigger → /sentiment-batch when either fires first:
      • --debounce seconds since last message (default 120s = 2 min)
      • --batch-limit messages accumulated    (default 50)

Usage:
    python chat.py                         # defaults (120s / 50 msgs)
    python chat.py --debounce 10           # 10-second timer for testing
    python chat.py --debounce 10 --batch-limit 5   # fire after 5 msgs too

    # Against a deployed URL:
    python chat.py --url https://your-deployed-url.com

Each turn you pick a role (sw / c) and type a message.
The batch result fires automatically after the timer or message limit.
Type 'reset' to start a new conversation, 'history' to review, 'batch' to force flush, 'quit' to exit.
"""

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
import requests


# ── Config ─────────────────────────────────────────────────────────────────────

ROLE_MAP = {"sw": "support_worker", "w": "support_worker", "c": "client"}

SENTIMENT_EMOJI = {
    "positive_satisfied":      "😊",
    "neutral":                 "😐",
    "frustrated_dissatisfied": "😤",
    "distressed_upset":        "😢",
    "confused_uncertain":      "😕",
    "engaged":                 "👍",
    "disengaged":              "😶",
}

RISK_COLOR = {
    "low":      "\033[32m",
    "medium":   "\033[33m",
    "high":     "\033[91m",
    "critical": "\033[31m",
}

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
CYAN  = "\033[36m"
WHITE = "\033[97m"
MAGENTA = "\033[35m"


# ── Print helpers ──────────────────────────────────────────────────────────────

def hr(char="─", width=64):
    print(DIM + char * width + RESET)


def print_batch_analysis(body: dict, trigger: str):
    """Print batch sentiment response (called when debounce or limit fires)."""
    count = body["messages_analysed"]
    start = body.get("period_start", "")[:19]
    end   = body.get("period_end",   "")[:19]

    print(f"\n{MAGENTA}{'═' * 64}{RESET}")
    print(f"{BOLD}{MAGENTA}  BATCH ANALYSIS  —  trigger: {trigger}{RESET}")
    print(f"{MAGENTA}  {count} messages  |  {start} → {end}{RESET}")
    print(f"{MAGENTA}{'═' * 64}{RESET}")

    for i, m in enumerate(body["messages"]):
        role_label = "SUPPORT WORKER" if m["role"] == "support_worker" else "CLIENT        "
        color = CYAN if m["role"] == "support_worker" else WHITE
        print(f"\n{color}{BOLD}  [{i}] {role_label}{RESET}  {DIM}{m['text'][:70]}{RESET}")

        s  = m["sentiment"]
        r  = m["risk"]
        bd = m["breakdown"]

        emoji  = SENTIMENT_EMOJI.get(s["label"], "")
        rcolor = RISK_COLOR.get(r["level"], "")

        print(f"      Sentiment : {emoji} {s['label'].replace('_', ' '):<26} ({s['confidence']:.0%})")
        print(f"      Risk      : {rcolor}{r['level'].upper():<8}{RESET}", end="")
        if r["indicators"]:
            print(f"  {DIM}{', '.join(r['indicators'][:2])}{RESET}", end="")
        print()

        bd_str = "\033[31mYES\033[0m" if bd["detected"] else "\033[32mNo\033[0m"
        print(f"      Breakdown : {bd_str}", end="")
        if bd["detected"] and bd["reasons"]:
            print(f"  {DIM}{bd['reasons'][0]}{RESET}", end="")
        print()

        outcome_colors = {"resolved": "\033[32m", "unresolved": "\033[31m", "pending": "\033[33m"}
        oc = outcome_colors.get(m["outcome"], "")
        print(f"      Outcome   : {oc}{m['outcome'].title()}{RESET}")

        if m.get("recommended_action"):
            print(f"      {BOLD}\033[91m⚠ Action  : {m['recommended_action']}{RESET}")

    print(f"\n{MAGENTA}{'═' * 64}{RESET}\n")


def print_message(role: str, text: str, turn: int):
    label = "SUPPORT WORKER" if role == "support_worker" else "CLIENT        "
    color = CYAN if role == "support_worker" else WHITE
    print(f"\n{color}{BOLD}[{turn}] {label}{RESET}  {text}")


# ── Batch buffer (shared between main thread and timer thread) ─────────────────

class BatchBuffer:
    """Thread-safe buffer that tracks messages and fires when a trigger is met."""

    def __init__(self, limit: int):
        self._msgs: list = []
        self._last_msg_time: float | None = None
        self._lock = threading.Lock()
        self.limit = limit

    def add(self, msg: dict) -> bool:
        """Add a message. Returns True if the 50-msg limit was just hit."""
        with self._lock:
            self._msgs.append(msg)
            self._last_msg_time = time.time()
            return len(self._msgs) >= self.limit

    def drain_if_idle(self, debounce_secs: float) -> list | None:
        """Called by timer thread. Returns messages to send if debounce fired, else None."""
        with self._lock:
            if not self._msgs or self._last_msg_time is None:
                return None
            if time.time() - self._last_msg_time >= debounce_secs:
                msgs = list(self._msgs)
                self._msgs.clear()
                self._last_msg_time = None
                return msgs
            return None

    def drain_all(self) -> list:
        """Force drain (used on limit hit or reset)."""
        with self._lock:
            msgs = list(self._msgs)
            self._msgs.clear()
            self._last_msg_time = None
            return msgs

    def size(self) -> int:
        with self._lock:
            return len(self._msgs)


# ── Batch API call ─────────────────────────────────────────────────────────────

def do_batch_call(msgs: list, batch_url: str, headers: dict, conv_id: str, trigger: str):
    if not msgs:
        return
    payload = {
        "conversation_id": conv_id,
        "provider_id":     "chat_tester",
        "messages":        msgs,
    }
    try:
        resp = requests.post(batch_url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        print_batch_analysis(resp.json(), trigger)
    except requests.exceptions.Timeout:
        print(f"\n{MAGENTA}[BATCH] Request timed out.{RESET}")
    except requests.exceptions.HTTPError as e:
        print(f"\n{MAGENTA}[BATCH] HTTP {resp.status_code}: {resp.text[:200]}{RESET}")
    except Exception as e:
        print(f"\n{MAGENTA}[BATCH] Error: {e}{RESET}")


# ── Timer thread ───────────────────────────────────────────────────────────────

def debounce_watcher(buffer: BatchBuffer, batch_url: str, headers: dict,
                     conv_id_ref: list, debounce_secs: float, stop_event: threading.Event):
    """Runs in background. Fires batch call when messages sit idle for debounce_secs."""
    while not stop_event.is_set():
        time.sleep(1)
        msgs = buffer.drain_if_idle(debounce_secs)
        if msgs:
            do_batch_call(msgs, batch_url, headers, conv_id_ref[0],
                          f"{int(debounce_secs)}s debounce")


# ── Main loop ──────────────────────────────────────────────────────────────────

def run(base_url: str, api_key: str, debounce_secs: float, batch_limit: int):
    batch_url = base_url.rstrip("/") + "/api/v1/sentiment-batch"
    headers = {"X-API-Key": api_key} if api_key else {}

    try:
        r = requests.get(base_url.rstrip("/") + "/health", timeout=5)
        r.raise_for_status()
        health = r.json()
        print(f"\n{BOLD}Sena Conversation Tester{RESET}")
        print(f"{DIM}Server : {base_url}  |  Model: {health.get('model', '?')}{RESET}")
        print(f"{DIM}Batch  : fires after {int(debounce_secs)}s idle  OR  {batch_limit} messages{RESET}")
    except Exception:
        print(f"\n\033[31mCould not reach server at {base_url}\033[0m")
        print(f"{DIM}Start it with:  uvicorn app.main:app --reload --port 8000{RESET}\n")
        sys.exit(1)

    print(f"\n{DIM}Commands:")
    print(f"  Role:  sw  (support worker)  |  c  (client)")
    print(f"  Other: reset  (new conversation)  |  history  |  batch  (force flush)  |  quit{RESET}\n")

    history    = []
    buffer     = BatchBuffer(limit=batch_limit)
    conv_id    = f"chat_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    conv_id_ref = [conv_id]
    turn       = 0

    stop_event = threading.Event()
    watcher = threading.Thread(
        target=debounce_watcher,
        args=(buffer, batch_url, headers, conv_id_ref, debounce_secs, stop_event),
        daemon=True,
    )
    watcher.start()

    while True:
        try:
            role_input = input(f"{DIM}Role [sw/c]: {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nFlushing buffer before exit...")
            msgs = buffer.drain_all()
            if msgs:
                do_batch_call(msgs, batch_url, headers, conv_id_ref[0], "exit flush")
            stop_event.set()
            print("Bye.")
            break

        if role_input in ("quit", "q", "exit"):
            msgs = buffer.drain_all()
            if msgs:
                do_batch_call(msgs, batch_url, headers, conv_id_ref[0], "exit flush")
            stop_event.set()
            print("Bye.")
            break

        if role_input in ("reset", "r"):
            msgs = buffer.drain_all()
            if msgs:
                print(f"{DIM}Flushing {len(msgs)} buffered messages before reset...{RESET}")
                do_batch_call(msgs, batch_url, headers, conv_id_ref[0], "reset flush")
            history = []
            turn = 0
            conv_id = f"chat_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            conv_id_ref[0] = conv_id
            print(f"\n{DIM}─── New conversation started ───{RESET}\n")
            continue

        if role_input == "history":
            if not history:
                print(f"{DIM}  (no history yet){RESET}")
            for i, m in enumerate(history):
                role_label = "SW" if m["role"] == "support_worker" else "CL"
                print(f"  {DIM}[{i+1}] {role_label}: {m['text']}{RESET}")
            continue

        if role_input in ("batch", "b"):
            msgs = buffer.drain_all()
            if msgs:
                do_batch_call(msgs, batch_url, headers, conv_id_ref[0], "manual flush")
            else:
                print(f"{DIM}  (buffer is empty){RESET}")
            continue

        role = ROLE_MAP.get(role_input)
        if not role:
            print(f"{DIM}  Use 'sw' for support worker or 'c' for client.{RESET}")
            continue

        try:
            role_label = "Support Worker" if role == "support_worker" else "Client"
            text = input(f"{DIM}Message ({role_label}): {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            stop_event.set()
            print("\nBye.")
            break

        if not text:
            continue

        turn += 1
        print_message(role, text, turn)

        ts = datetime.now(timezone.utc).isoformat()
        current_message = {"role": role, "text": text, "timestamp": ts}
        history.append(current_message)

        # ── Add to batch buffer — check 50-msg limit ───────────────────────────
        limit_hit = buffer.add(current_message)
        remaining = batch_limit - buffer.size()
        print(f"  {DIM}[batch buffer: {buffer.size()}/{batch_limit} msgs", end="")
        if remaining <= 10:
            print(f"  — {remaining} until limit flush", end="")
        print(f"]{RESET}")

        if limit_hit:
            msgs = buffer.drain_all()
            print(f"\n{MAGENTA}  ► {batch_limit}-message limit reached — sending batch...{RESET}")
            do_batch_call(msgs, batch_url, headers, conv_id_ref[0], f"{batch_limit}-message limit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interactive Sena conversation tester")
    parser.add_argument("--url",         default="http://localhost:8000", help="API base URL")
    parser.add_argument("--key",         default="",  help="API key (if configured)")
    parser.add_argument("--debounce",    default=120, type=int, help="Seconds of idle before batch fires (default 120)")
    parser.add_argument("--batch-limit", default=50,  type=int, help="Max messages before batch fires (default 50)")
    args = parser.parse_args()
    run(args.url, args.key, args.debounce, args.batch_limit)
