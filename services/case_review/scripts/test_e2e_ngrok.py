#!/usr/bin/env python3
"""
SENA AI — End-to-end smoke test via ngrok.

Tests (in order):
  1. Health checks (case_review + onboarding)
  2. Onboarding routing smoke (405 = route exists)
  3. POST /case-review/v1/case-review/voice/session  (REST)
  4. WSS /case-review/ws/case-review/voice/<id>      (text-turn mode)
  5. WSS audio stream test (synthetic PCM — no ffmpeg required)

Requirements (already installed in case_review venv):
  pip install httpx websockets

Run from repo root:
  python services/case_review/scripts/test_e2e_ngrok.py

To test with the real MP3 audio file (requires ffmpeg):
  ffmpeg -i luvvoice.com-20260619-HYolcX.mp3 -f s16le -ar 16000 -ac 1 test_audio.raw
  python services/case_review/scripts/test_e2e_ngrok.py --audio test_audio.raw
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
from pathlib import Path

import httpx
import websockets

# ── Config ──────────────────────────────────────────────────────────────────
NGROK   = "https://astride-supremacy-constant.ngrok-free.dev"
WS_BASE = "wss://astride-supremacy-constant.ngrok-free.dev"

TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
WORKER_ID = "bbbbbbbb-0000-0000-0000-000000000002"
CLIENT_ID = "liam-001"          # any string — no DB lookup in voice flow
SHIFT_ID  = "shift-test-001"   # any string

REST_HEADERS = {
    "X-Tenant-Id":      TENANT_ID,
    "X-Participant-Id": WORKER_ID,
    "X-User-Roles":     "worker",
    "Content-Type":     "application/json",
}

# Realistic case-note dictation turns (enough to trigger field extraction)
TURNS = [
    "I was supporting Liam with his morning routine today.",
    "His mood was settled and he was cooperative throughout.",
    "I assisted with personal hygiene, meal preparation and medication.",
    "Session duration was approximately 2 hours, no incidents to report.",
    "yes that covers everything for today",
]

PCM_SAMPLE_RATE = 16_000
PCM_CHUNK_BYTES = 4_096


# ── Helpers ──────────────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n{'='*62}\n  {title}\n{'='*62}")


def _make_pcm_sine(duration_sec: float = 1.5, hz: float = 440.0) -> bytes:
    """Synthetic PCM 16-bit mono sine wave — stdlib only, no ffmpeg needed."""
    n = int(PCM_SAMPLE_RATE * duration_sec)
    samples = (int(32767 * math.sin(2 * math.pi * hz * i / PCM_SAMPLE_RATE)) for i in range(n))
    return struct.pack(f"<{n}h", *samples)


def _load_raw_audio(path: str) -> bytes:
    """Load a pre-converted .raw PCM file (from ffmpeg -f s16le -ar 16000 -ac 1)."""
    data = Path(path).read_bytes()
    print(f"  Loaded raw PCM: {len(data)} bytes ({len(data)/32000:.1f}s)")
    return data


# ── Test steps ───────────────────────────────────────────────────────────────

async def step_health() -> bool:
    _section("1 — HEALTH CHECKS")
    checks = {
        "case_review": "/case-review/v1/restrictive-practices/health",
        "onboarding":  "/onboarding/health/live",
    }
    ok = True
    async with httpx.AsyncClient(timeout=15) as c:
        for svc, path in checks.items():
            try:
                r = await c.get(f"{NGROK}{path}")
                icon = "✅" if r.status_code == 200 else "⚠️ "
                print(f"  {icon} {svc}: HTTP {r.status_code}  {r.text[:80]}")
                if r.status_code != 200:
                    ok = False
            except Exception as e:
                print(f"  ❌ {svc}: {e}")
                ok = False
    return ok


async def step_onboarding_routing() -> bool:
    _section("2 — ONBOARDING ROUTING (expect 405 = route exists)")
    url = f"{NGROK}/onboarding/v1/onboarding/session"
    async with httpx.AsyncClient(timeout=10) as c:
        try:
            r = await c.get(url)
            if r.status_code == 405:
                print(f"  ✅ 405 Method Not Allowed — route alive")
                return True
            print(f"  ❌ {r.status_code} — {r.text[:80]}")
            return False
        except Exception as e:
            print(f"  ❌ {e}")
            return False


async def step_create_session() -> dict | None:
    _section("3 — CREATE VOICE SESSION (REST)")
    url  = f"{NGROK}/case-review/v1/case-review/voice/session"
    body = {"client_id": CLIENT_ID, "shift_id": SHIFT_ID, "initial_values": {}}
    print(f"  POST {url}")
    print(f"  Body: {json.dumps(body)}")
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post(url, json=body, headers=REST_HEADERS)
            print(f"  Status: {r.status_code}")
            if r.status_code not in (200, 201):
                print(f"  ❌ Body: {r.text[:300]}")
                return None
            data = r.json()
            print(f"  ✅ session_id = {data.get('session_id')}")
            print(f"     ws_url     = {data.get('ws_url')}")
            return data
        except Exception as e:
            print(f"  ❌ {e}")
            return None


async def _ws_connect(ws_path: str) -> websockets.WebSocketClientProtocol:
    """Build full WS URL (prepend /case-review) and connect.

    participant_id MUST be CLIENT_ID (= body.client_id from session create),
    not the worker UUID. assert_session_owner checks it against state.participant_id.
    """
    full = (
        f"{WS_BASE}/case-review{ws_path}"
        f"?tenant_id={TENANT_ID}&participant_id={CLIENT_ID}&roles=worker"
    )
    print(f"  WS URL: {full}")
    return await websockets.connect(full, open_timeout=20, ping_timeout=30)


async def _wait_for_ready(ws: websockets.WebSocketClientProtocol, timeout: float = 20) -> bool:
    """Drain frames until {type: ready}."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=deadline - asyncio.get_event_loop().time())
        except asyncio.TimeoutError:
            print("  ❌ Timed out waiting for 'ready'")
            return False
        if isinstance(msg, bytes):
            continue
        ev = json.loads(msg)
        t  = ev.get("type")
        if t == "ready":
            print(f"  ✅ ready — coverage={ev.get('coverage')}")
            return True
        if t == "error":
            print(f"  ❌ error on ready: {ev.get('message')}")
            return False
        print(f"  [{t}] (pre-ready frame)")
    print("  ❌ Timed out waiting for 'ready'")
    return False


async def step_ws_text_turns(ws_path: str) -> dict:
    _section("4 — WEBSOCKET TEXT-TURN TEST (no mic required)")
    results: dict = {"agent_responses": [], "field_updates": [], "complete": False}

    ws = await _ws_connect(ws_path)
    try:
        if not await _wait_for_ready(ws):
            return results

        done = asyncio.Event()

        async def listen() -> None:
            while not done.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=15)
                except asyncio.TimeoutError:
                    break
                if isinstance(msg, bytes):
                    print(f"    [AUDIO ← agent] {len(msg)} bytes")
                    continue
                ev = json.loads(msg)
                t  = ev.get("type")
                if t == "agent_said":
                    txt = ev.get("text", "")
                    results["agent_responses"].append(txt)
                    print(f"    AGENT: {txt}")
                elif t == "user_said":
                    print(f"    USER:  {ev.get('text', '')}")
                elif t in ("field_updated", "field_update"):
                    results["field_updates"].append(ev)
                    fid = f"{ev.get('section_id')}.{ev.get('field_id')}"
                    print(f"    FIELD: {fid} = {ev.get('value')!r}")
                elif t == "session_complete":
                    results["complete"] = True
                    print(f"  ✅ session_complete")
                    done.set()
                elif t == "turn_start":
                    print(f"    [turn_start — agent speaking]")
                elif t == "turn_complete":
                    print(f"    [turn_complete]")
                elif t == "interrupted":
                    print(f"    [interrupted]")
                elif t == "error":
                    print(f"  ❌ error: {ev.get('message')}")
                    done.set()
                else:
                    print(f"    [{t}] {json.dumps(ev)[:100]}")

        listen_task = asyncio.create_task(listen())

        for turn in TURNS:
            if done.is_set():
                break
            print(f"\n  → Sending turn: {turn!r}")
            await ws.send(json.dumps({"type": "user_text", "text": turn}))
            # Give agent up to 12s to respond before next turn
            try:
                await asyncio.wait_for(asyncio.shield(done.wait()), timeout=12)
            except asyncio.TimeoutError:
                pass

        # Final drain
        try:
            await asyncio.wait_for(listen_task, timeout=20)
        except asyncio.TimeoutError:
            listen_task.cancel()
    finally:
        await ws.close()

    return results


async def step_ws_audio_stream(ws_path: str, raw_pcm: bytes | None = None) -> bool:
    _section("5 — WEBSOCKET BINARY AUDIO STREAM TEST")

    if raw_pcm is None:
        print("  No .raw file provided — using synthetic 440Hz sine wave (1.5s, 16-bit, 16kHz mono)")
        print("  (To use real audio: ffmpeg -i file.mp3 -f s16le -ar 16000 -ac 1 out.raw)")
        raw_pcm = _make_pcm_sine(1.5)
    else:
        print(f"  Real PCM loaded: {len(raw_pcm)} bytes ({len(raw_pcm)/32000:.1f}s)")

    got_response = False
    ws = await _ws_connect(ws_path)
    try:
        if not await _wait_for_ready(ws):
            return False

        chunks = [raw_pcm[i:i+PCM_CHUNK_BYTES] for i in range(0, len(raw_pcm), PCM_CHUNK_BYTES)]
        print(f"  Streaming {len(chunks)} binary PCM chunks ({len(raw_pcm)} bytes total)...")

        received = asyncio.Event()

        async def listen() -> None:
            nonlocal got_response
            while not received.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=25)
                except asyncio.TimeoutError:
                    print("  ⚠️ No agent response within 25s")
                    received.set()
                    return
                if isinstance(msg, bytes):
                    print(f"    [AUDIO ← agent] {len(msg)} bytes  ✅ audio pipeline working")
                    got_response = True
                    received.set()
                    return
                ev = json.loads(msg)
                t  = ev.get("type")
                print(f"    [{t}] {ev.get('text', json.dumps(ev)[:80])}")
                if t in ("turn_start", "agent_said", "session_complete"):
                    got_response = True
                    received.set()
                    return
                if t == "error":
                    received.set()
                    return

        listen_task = asyncio.create_task(listen())

        for i, chunk in enumerate(chunks, 1):
            if received.is_set():
                break
            try:
                await ws.send(chunk)           # raw binary — NOT JSON
            except Exception:
                # WS closed mid-stream (server crashed / Gemini auth failure)
                break
            await asyncio.sleep(0.08)          # ~12.5 chunks/s ≈ real-time 16kHz
            if i % 10 == 0:
                print(f"    … {i}/{len(chunks)} chunks sent")

        try:
            await asyncio.wait_for(listen_task, timeout=25)
        except asyncio.TimeoutError:
            listen_task.cancel()
    finally:
        await ws.close()

    return got_response


# ── Orchestrator ─────────────────────────────────────────────────────────────

async def main(raw_audio_path: str | None = None) -> None:
    print("\n" + "█" * 62)
    print("  SENA AI — END-TO-END SMOKE TEST")
    print(f"  Target : {NGROK}")
    print(f"  Tenant : {TENANT_ID}")
    print(f"  Worker : {WORKER_ID}")
    print("█" * 62)

    passed: list[str] = []
    failed: list[str] = []

    def record(label: str, ok: bool) -> None:
        (passed if ok else failed).append(label)

    # 1. Health
    record("Health checks (case_review + onboarding)", await step_health())

    # 2. Onboarding routing
    record("Onboarding nginx routing", await step_onboarding_routing())

    # 3. Create voice session
    session = await step_create_session()
    if not session:
        failed.append("Voice session create (REST)")
        _section("RESULTS — EARLY EXIT")
        for p in passed: print(f"  ✅ {p}")
        for f in failed: print(f"  ❌ {f}")
        print("\n  ❌ Cannot run WS tests without a session.\n"
              "     Is case_review service running on port 8084?\n")
        sys.exit(1)
    passed.append("Voice session create (REST)")

    # 4. Text turn WS test
    text = await step_ws_text_turns(session["ws_url"])
    record("WS text turns — voice agent responded", bool(text["agent_responses"]))
    if text["field_updates"]:
        passed.append(f"Field extraction ({len(text['field_updates'])} fields auto-filled)")
    if text["complete"]:
        passed.append("Session completed (all fields filled)")

    # 5. Audio stream WS test (fresh session)
    session2 = await step_create_session()
    if session2:
        raw_pcm = _load_raw_audio(raw_audio_path) if raw_audio_path else None
        record("WS binary audio stream — agent responded", await step_ws_audio_stream(session2["ws_url"], raw_pcm))
    else:
        failed.append("Second session create (for audio test)")

    # Summary
    _section("FINAL RESULTS")
    for p in passed:
        print(f"  ✅ {p}")
    for f in failed:
        print(f"  ❌ {f}")

    total = len(passed) + len(failed)
    if not failed:
        print(f"\n  🎉 ALL {total} CHECKS PASSED — pipeline is working end-to-end\n")
    else:
        print(f"\n  ❌ {len(failed)}/{total} FAILED\n")

    print("  ─── How to use the real MP3 audio file ───────────────────────")
    print("  Install ffmpeg: https://ffmpeg.org/download.html")
    print("  Convert:  ffmpeg -i luvvoice.com-20260619-HYolcX.mp3 -f s16le -ar 16000 -ac 1 test.raw")
    print("  Run:      python services/case_review/scripts/test_e2e_ngrok.py --audio test.raw\n")


if __name__ == "__main__":
    audio_path = None
    if "--audio" in sys.argv:
        idx = sys.argv.index("--audio")
        if idx + 1 < len(sys.argv):
            audio_path = sys.argv[idx + 1]
            if not Path(audio_path).exists():
                print(f"ERROR: audio file not found: {audio_path}")
                sys.exit(1)

    asyncio.run(main(audio_path))
