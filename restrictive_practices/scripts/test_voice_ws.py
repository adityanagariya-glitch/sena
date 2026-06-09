"""
Voice WS test script — text-mode (no mic needed).
Replaces WS_URL with the value from POST /voice/session before running.
"""
import asyncio
import json
import sys

import websockets

WS_URL = "ws://127.0.0.1:8084/v1/restrictive-practices/voice/ws/726a25e5-32c3-4d66-8986-790f922a70e8?token=121d9f36-16a8-4d25-b596-9f573b1a121b"


async def main():
    print(f"Connecting to: {WS_URL[:80]}...")
    try:
        async with websockets.connect(WS_URL, open_timeout=10) as ws:
            print("Connected.\n")

            turns = [
                "I was supporting Liam with his morning routine",
                "His mood was settled and he was cooperative",
                "No injuries, no concerns",
                "yes that's everything done",
            ]

            done = asyncio.Event()

            async def receive():
                try:
                    async for msg in ws:
                        if isinstance(msg, bytes):
                            print(f"  [AUDIO] {len(msg)} bytes received")
                        else:
                            ev = json.loads(msg)
                            t = ev.get("type")
                            if t == "error":
                                print(f"\n  !! SERVER ERROR: {ev.get('message')}")
                                print(f"  Detail:\n{ev.get('detail', '')}")
                                done.set()
                                return
                            elif t == "field_updated":
                                print(f"  FIELD: {ev['section_id']}.{ev['field_id']} = {ev.get('value')!r}")
                            elif t == "user_said":
                                print(f"  USER:  {ev['text']!r}")
                            elif t == "agent_said":
                                print(f"  AGENT: {ev['text']!r}")
                            elif t == "session_complete":
                                print(f"\n  ✓ SESSION COMPLETE")
                                print(f"  Payload keys: {list(ev['payload'].keys())}")
                                done.set()
                                return
                            elif t == "turn_complete":
                                print(f"  [turn_complete — agent finished speaking]")
                            elif t == "turn_start":
                                print(f"  [turn_start — agent speaking...]")
                            elif t == "interrupted":
                                print(f"  [interrupted]")
                            else:
                                print(f"  [{t}] {json.dumps(ev)[:120]}")
                except websockets.exceptions.ConnectionClosedError as e:
                    print(f"\n  WS closed: code={e.rcvd.code if e.rcvd else '?'} reason={e.rcvd.reason if e.rcvd else ''}")
                    done.set()
                except Exception as e:
                    print(f"\n  receive() error: {e}")
                    done.set()

            recv_task = asyncio.create_task(receive())

            for turn in turns:
                # Wait up to 15s for agent to respond, or until done
                try:
                    await asyncio.wait_for(asyncio.shield(done.wait()), timeout=15)
                    if done.is_set():
                        break
                except asyncio.TimeoutError:
                    pass

                if done.is_set():
                    break

                print(f"\n→ Sending: {turn!r}")
                try:
                    await ws.send(json.dumps({"type": "user_text", "text": turn}))
                except websockets.exceptions.ConnectionClosedError:
                    print("  WS closed before we could send.")
                    break

            try:
                await asyncio.wait_for(recv_task, timeout=30)
            except asyncio.TimeoutError:
                print("  Timed out waiting for final response.")

    except websockets.exceptions.InvalidURI:
        print(f"ERROR: WS_URL is not set. Edit this script and paste the ws_url from POST /voice/session.")
        sys.exit(1)
    except OSError as e:
        print(f"ERROR: Could not connect — {e}")
        print("Check the server is running: uvicorn main:app --reload --port 8084")
        sys.exit(1)


if __name__ == "__main__":
    if "REPLACE_WITH" in WS_URL:
        print("ERROR: Edit test_voice_ws.py and set WS_URL to the ws_url from POST /voice/session")
        sys.exit(1)
    asyncio.run(main())
