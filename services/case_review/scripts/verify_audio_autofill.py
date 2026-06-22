#!/usr/bin/env python3
"""Verify the REAL case-note chain: audio -> transcription -> field auto-fill.

The voice flow is MOBILE-AUTHORITATIVE: the server transcribes, then emits a
`tool_request` (the update_field call) and BLOCKS up to 5s for the client to
reply with a `tool_response`. A passive listener sees update_field time out.
This harness PLAYS THE PHONE: it ACKs every tool_request with {ok:true} so the
agent proceeds, and records each update_field call as a confirmed auto-fill.

Contract (from shared/.../voice/mobile_bridge.py + gemini_live.py):
  server -> client : {"type":"tool_request","request_id":id,"tool":"update_field","args":{section,field,value,...}}
  client -> server : {"type":"tool_response","request_id":id,"result":{"ok":true}}

Run from repo root:
  ffmpeg -y -i luvvoice.com-20260619-HYolcX.mp3 -f s16le -ar 16000 -ac 1 test.raw
  python services/case_review/scripts/verify_audio_autofill.py test.raw
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import websockets

NGROK = "https://astride-supremacy-constant.ngrok-free.dev"
WS_BASE = "wss://astride-supremacy-constant.ngrok-free.dev"
TENANT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CLIENT_ID = "liam-001"
SHIFT_ID = "shift-test-001"
REST_HEADERS = {
    "X-Tenant-Id": TENANT_ID,
    "X-Participant-Id": CLIENT_ID,
    "X-User-Roles": "worker",
    "Content-Type": "application/json",
}
RATE = 16_000
CHUNK = 3_200            # 0.1s of 16kHz 16-bit mono
STREAM_SECONDS = 75      # send most of the dictation
DRAIN_AFTER = 25         # listen after audio ends for late fills + finalize


async def create_session() -> dict | None:
    url = f"{NGROK}/case-review/v1/case-review/voice/session"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(url, json={"client_id": CLIENT_ID, "shift_id": SHIFT_ID,
                                    "initial_values": {}}, headers=REST_HEADERS)
        if r.status_code not in (200, 201):
            print(f"session create failed: {r.status_code} {r.text[:200]}")
            return None
        return r.json()


async def run(raw_path: str) -> None:
    pcm = Path(raw_path).read_bytes()
    print(f"PCM: {len(pcm):,} bytes (~{len(pcm)/32000:.1f}s)")
    session = await create_session()
    if not session:
        return
    url = (f"{WS_BASE}/case-review{session['ws_url']}"
           f"?tenant_id={TENANT_ID}&participant_id={CLIENT_ID}&roles=worker")
    print(f"WS: {url}\n")

    cap = {"user_said": [], "agent_said": [], "tool_requests": [], "fills": [], "errors": []}
    greeting_done = asyncio.Event()
    stop = asyncio.Event()

    async with websockets.connect(url, open_timeout=20, ping_timeout=40, max_size=None) as ws:

        async def listen() -> None:
            while not stop.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    return
                if isinstance(msg, bytes):
                    continue
                ev = json.loads(msg)
                t = ev.get("type")
                if t == "ready":
                    print("  [ready] session live")
                elif t == "turn_complete":
                    greeting_done.set()
                elif t == "user_said":
                    cap["user_said"].append(ev.get("text", ""))
                    print(f"  USER: {ev.get('text','')!r}")
                elif t == "agent_said":
                    cap["agent_said"].append(ev.get("text", ""))
                    print(f"  AGENT: {ev.get('text','')!r}")
                elif t == "tool_request":
                    tool = ev.get("tool")
                    args = ev.get("args", {})
                    rid = ev.get("request_id")
                    cap["tool_requests"].append({"tool": tool, "args": args})
                    if tool == "update_field":
                        sec = args.get("section") or args.get("section_id")
                        fld = args.get("field") or args.get("field_id")
                        val = args.get("value")
                        cap["fills"].append((sec, fld, val))
                        print(f"  >>> AUTOFILL update_field: {sec}.{fld} = {val!r}")
                    else:
                        print(f"  [tool_request] {tool} args={json.dumps(args)[:120]}")
                    # PLAY THE PHONE: ack so the agent proceeds (else 5s timeout).
                    await ws.send(json.dumps({
                        "type": "tool_response", "request_id": rid, "result": {"ok": True},
                    }))
                elif t in ("session_complete", "step_complete"):
                    print(f"  [{t}]")
                elif t == "error":
                    cap["errors"].append(ev)
                    print(f"  ERROR: {ev}")
                    stop.set()
                    return

        listener = asyncio.create_task(listen())

        try:
            await asyncio.wait_for(greeting_done.wait(), timeout=10)
            print("  -- greeting done; streaming real audio --\n")
        except asyncio.TimeoutError:
            print("  -- no greeting in 10s; streaming anyway --\n")

        sent = 0
        max_bytes = STREAM_SECONDS * RATE * 2
        for i in range(0, min(len(pcm), max_bytes), CHUNK):
            if stop.is_set():
                break
            try:
                await ws.send(pcm[i:i + CHUNK])
            except Exception:
                break
            sent += 1
            await asyncio.sleep(0.1)
            if sent % 100 == 0:
                print(f"    .. streamed {sent*CHUNK/32000:.0f}s")

        # Signal end-of-utterance so Gemini flushes + the agent acts on the tail.
        try:
            await ws.send(json.dumps({"type": "audio_end"}))
        except Exception:
            pass
        print(f"\n  -- audio sent ({sent*CHUNK/32000:.0f}s); draining {DRAIN_AFTER}s --\n")

        try:
            await asyncio.wait_for(stop.wait(), timeout=DRAIN_AFTER)
        except asyncio.TimeoutError:
            pass
        stop.set()
        listener.cancel()

    # ── Verdict (ASCII only — Windows cp1252 console) ───────────────────────────
    print("\n" + "=" * 60)
    print("  AUDIO -> TRANSCRIPT -> AUTO-FILL VERIFICATION")
    print("=" * 60)
    ok_t = bool(cap["user_said"])
    ok_f = bool(cap["fills"])
    ok_a = bool(cap["agent_said"])
    mark = lambda b: "[OK]" if b else "[XX]"  # noqa: E731
    print(f"  {mark(ok_t)} Transcription (user_said):     {len(cap['user_said'])} utterances")
    print(f"  {mark(ok_f)} Auto-fill (update_field calls): {len(cap['fills'])} fields")
    print(f"  {mark(ok_a)} Agent response (agent_said):   {len(cap['agent_said'])} turns")
    print(f"       total tool_requests: {len(cap['tool_requests'])}")
    if cap["fills"]:
        print("\n  Case-note fields auto-filled FROM AUDIO:")
        for sec, fld, val in cap["fills"]:
            sval = str(val)
            print(f"    - {sec}.{fld} = {sval[:90]!r}")
    if cap["errors"]:
        print(f"\n  ERRORS: {cap['errors']}")
    print()
    if ok_t and ok_f:
        print("  RESULT: FULL CHAIN VERIFIED -- audio transcribed AND auto-filled case-note fields.\n")
    elif ok_t and not ok_f:
        print("  RESULT: transcription works but agent never called update_field (prompt/tool issue).\n")
    else:
        print("  RESULT: no transcription -- audio not processed (check SDK/restart).\n")


if __name__ == "__main__":
    if len(sys.argv) < 2 or not Path(sys.argv[1]).exists():
        print("usage: python verify_audio_autofill.py <test.raw>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
