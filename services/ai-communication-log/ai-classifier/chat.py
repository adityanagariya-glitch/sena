"""
Interactive conversation tester for the Sena classifier.

Usage:
    python chat.py

    # Against a deployed URL:
    python chat.py --url https://your-deployed-url.com

Each turn you pick a role (sw / client), type a message,
and see the full analysis. History builds automatically.
Type 'reset' to start a new conversation, 'quit' to exit.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
import requests


# ── Config ─────────────────────────────────────────────────────────────────────

ROLE_MAP = {"sw": "support_worker", "w": "support_worker", "c": "client"}

SENTIMENT_EMOJI = {
    "positive_satisfied":    "😊",
    "neutral":               "😐",
    "frustrated_dissatisfied": "😤",
    "distressed_upset":      "😢",
    "confused_uncertain":    "😕",
    "engaged":               "👍",
    "disengaged":            "😶",
}

RISK_COLOR = {
    "low":      "\033[32m",   # green
    "medium":   "\033[33m",   # yellow
    "high":     "\033[91m",   # orange-red
    "critical": "\033[31m",   # red
}

LABEL_COLOR = {
    "normal":       "\033[32m",
    "inappropriate":"\033[33m",
    "emergency":    "\033[31m",
}

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
CYAN  = "\033[36m"
WHITE = "\033[97m"


# ── Printing helpers ───────────────────────────────────────────────────────────

def hr(char="─", width=60):
    print(DIM + char * width + RESET)


def print_analysis(body: dict):
    hr()

    # NDIS compliance labels
    print(f"{BOLD}  Classifications:{RESET}")
    for c in body["classifications"]:
        color = LABEL_COLOR.get(c["label"], "")
        bar = "█" * int(c["confidence"] * 10)
        print(f"    {color}{c['label'].upper():<16}{RESET}  {bar:<10}  {c['confidence']:.0%}")
        print(f"    {DIM}  → {c['reason']}{RESET}")

    # Sentiment
    s = body["sentiment"]
    emoji = SENTIMENT_EMOJI.get(s["label"], "")
    print(f"\n{BOLD}  Sentiment:{RESET}  {emoji} {s['label'].replace('_', ' ').title()}  ({s['confidence']:.0%})")
    print(f"    {DIM}→ {s['reason']}{RESET}")

    # Risk
    r = body["risk"]
    rcolor = RISK_COLOR.get(r["level"], "")
    print(f"\n{BOLD}  Risk:{RESET}       {rcolor}{r['level'].upper()}{RESET}")
    if r["indicators"]:
        for ind in r["indicators"]:
            print(f"    {DIM}• {ind}{RESET}")
    print(f"    {DIM}→ {r['reason']}{RESET}")

    # Breakdown
    bd = body["breakdown"]
    detected_str = f"\033[31mYES\033[0m" if bd["detected"] else f"\033[32mNo\033[0m"
    print(f"\n{BOLD}  Breakdown:{RESET}  {detected_str}")
    if bd["detected"]:
        for reason in bd["reasons"]:
            print(f"    {DIM}• {reason}{RESET}")

    # Outcome
    outcome_colors = {"resolved": "\033[32m", "unresolved": "\033[31m", "pending": "\033[33m"}
    oc = outcome_colors.get(body["outcome"], "")
    print(f"\n{BOLD}  Outcome:{RESET}    {oc}{body['outcome'].title()}{RESET}")

    # Recommended action
    if body.get("recommended_action"):
        print(f"\n{BOLD}\033[91m  ⚠ Action:{RESET}    {body['recommended_action']}")

    # Footer
    uncertain_note = f"  {DIM}(is_uncertain=True — model confidence low){RESET}" if body["is_uncertain"] else ""
    print(f"\n  {DIM}Messages analysed: {body['messages_analysed']}  |  {body['analysed_at'][:19]}{RESET}{uncertain_note}")
    hr()


def print_message(role: str, text: str, turn: int):
    label = "SUPPORT WORKER" if role == "support_worker" else "CLIENT        "
    color = CYAN if role == "support_worker" else WHITE
    print(f"\n{color}{BOLD}[{turn}] {label}{RESET}  {text}")


# ── Main loop ──────────────────────────────────────────────────────────────────

def run(base_url: str, api_key: str):
    classify_url = base_url.rstrip("/") + "/api/v1/classify"
    headers = {"X-API-Key": api_key} if api_key else {}

    # Check server is up
    try:
        r = requests.get(base_url.rstrip("/") + "/health", timeout=5)
        r.raise_for_status()
        health = r.json()
        print(f"\n{BOLD}Sena Conversation Tester{RESET}")
        print(f"{DIM}Server: {base_url}  |  Model: {health.get('model', '?')}{RESET}")
    except Exception as e:
        print(f"\n\033[31mCould not reach server at {base_url}\033[0m")
        print(f"{DIM}Start it with:  uvicorn app.main:app --reload --port 8000{RESET}\n")
        sys.exit(1)

    print(f"\n{DIM}Commands:")
    print(f"  Role:  sw  (support worker)  |  c  (client)")
    print(f"  Other: reset  (new conversation)  |  history  |  quit{RESET}\n")

    history = []
    conv_id = f"chat_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    turn = 0

    while True:
        # ── Role selection ─────────────────────────────────────────────────────
        try:
            role_input = input(f"{DIM}Role [sw/c]: {RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if role_input in ("quit", "q", "exit"):
            print("Bye.")
            break

        if role_input in ("reset", "r"):
            history = []
            turn = 0
            conv_id = f"chat_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            print(f"\n{DIM}─── New conversation started ───{RESET}\n")
            continue

        if role_input == "history":
            if not history:
                print(f"{DIM}  (no history yet){RESET}")
            for i, m in enumerate(history):
                role_label = "SW" if m["role"] == "support_worker" else "CL"
                print(f"  {DIM}[{i+1}] {role_label}: {m['text']}{RESET}")
            continue

        role = ROLE_MAP.get(role_input)
        if not role:
            print(f"{DIM}  Use 'sw' for support worker or 'c' for client.{RESET}")
            continue

        # ── Message input ──────────────────────────────────────────────────────
        try:
            role_label = "Support Worker" if role == "support_worker" else "Client"
            text = input(f"{DIM}Message ({role_label}): {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not text:
            continue

        turn += 1
        print_message(role, text, turn)

        ts = datetime.now(timezone.utc).isoformat()
        current_message = {"role": role, "text": text, "timestamp": ts}

        # ── Call classifier ────────────────────────────────────────────────────
        payload = {
            "conversation_id": conv_id,
            "provider_id":     "chat_tester",
            "current_message": current_message,
            "history":         history,
        }

        try:
            resp = requests.post(classify_url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            body = resp.json()
        except requests.exceptions.Timeout:
            print(f"\033[31m  Request timed out — is the server running?\033[0m")
            continue
        except requests.exceptions.HTTPError as e:
            print(f"\033[31m  HTTP {resp.status_code}: {resp.text[:200]}\033[0m")
            continue
        except Exception as e:
            print(f"\033[31m  Error: {e}\033[0m")
            continue

        print_analysis(body)

        # Add to history for next turn
        history.append(current_message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interactive Sena conversation tester")
    parser.add_argument("--url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--key", default="", help="API key (if configured)")
    args = parser.parse_args()
    run(args.url, args.key)
