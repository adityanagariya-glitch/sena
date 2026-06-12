"""End-to-end smoke test for the restrictive-practice case-review API.

Runs the full "voice note → structured draft → compliance verdict" cycle
against a running instance:

    1. GET  /v1/restrictive-practices/health          (preflight)
    2. POST /v1/restrictive-practices/draft            (transcript -> structured note)
    3. POST /v1/restrictive-practices/evaluate         (structured note -> RP verdict)

Usage:
    # 1) local uvicorn:
    uvicorn main:create_app --factory --port 8084
    python test.py

    # 2) through the nginx gateway (docker compose), HTTP on host port 8080:
    SENA_TEST_BASE_URL=http://localhost:8080/case-review python test.py

    # 3) public URL (TLS), with Basic auth if enabled on the server:
    SENA_TEST_BASE_URL=https://dev-api.isena.org/case-review \
    SENA_AI_BASIC_AUTH_USER=... SENA_AI_BASIC_AUTH_PASSWORD=... python test.py

Config via env vars:
    SENA_TEST_BASE_URL          default http://127.0.0.1:8084 (no trailing slash needed).
                                Point at the gateway prefix (.../case-review) and the script
                                appends /v1/restrictive-practices automatically.
    SENA_AI_BASIC_AUTH_USER     optional — set only if the server enforces basic auth
    SENA_AI_BASIC_AUTH_PASSWORD
"""

import json
import os
import sys
import uuid

import httpx

BASE_URL = os.getenv("SENA_TEST_BASE_URL", "http://127.0.0.1:8084").rstrip("/")
RP = f"{BASE_URL}/v1/restrictive-practices"

_user = os.getenv("SENA_AI_BASIC_AUTH_USER")
_pw = os.getenv("SENA_AI_BASIC_AUTH_PASSWORD")
AUTH = (_user, _pw) if _user and _pw else None

# Fields shared between CaseDraftResponse (/draft output) and CaseNoteInput
# (/evaluate input). We copy these straight from the draft to mimic the real
# flow: worker records voice -> reviews the AI draft -> submits it for evaluation.
_CARRY_FIELDS = [
    "client_id", "worker_id", "shift_date", "shift_time", "worker_position",
    "describe", "assisted", "practised_skill",
    "participants_level_of_independence", "observations",
    "mood", "behavioural_events", "any_concerns",
    "what_went_well", "what_needs_further_support", "participant_comments",
    "medication_reminders_given", "safety_hazards_observed", "any_injuries",
    "injury_description", "carer_feedback", "incident_occurred",
    "transcript", "uploaded_documents",
]

TRANSCRIPT = (
    "I had my shift with Mel today from 9:00am to 3:00pm. When I first arrived, his family "
    "mentioned he'd been pretty frustrated all morning. I noticed right away that he was a bit "
    "more withdrawn and speaking a lot quieter than he usually does. He let me know that he was "
    "feeling upset after getting into an argument with his sibling earlier about his gaming. Even "
    "though he was frustrated, he did a great job staying calm, was very receptive to support, and "
    "was still happy to go ahead with the activities we had planned. We spent a good portion of the "
    "morning focussing on emotional processing. I made sure to actively listen and offer reassurance, "
    "and we had some really open discussions about how to express emotions and handle it when family "
    "members have differing opinions. Mel responded really well to this and visibly relaxed as the day "
    "went on. For our activities, I supported him with transport out into the community. We went to a "
    "cafe, and he was incredibly independent. He'd already handled all his personal care before leaving "
    "home, and at the cafe, he ordered his own food and drinks without needing my help. Afterward, we "
    "headed over to the Inspiring Disability and Youth Services office for some social engagement. I was "
    "really impressed with his progress today, especially with his emotional regulation and communication. "
    "Even when he was talking about the family conflict, he kept an appropriate tone, stayed regulated, and "
    "reflected on his feelings without escalating. He also showed a lot more confidence in group settings "
    "than I've seen on previous community access shifts. He was initiating conversations with peers and "
    "staff with very little prompting. Once we got on to the topic of anime and gaming, his mood completely "
    "lifted. He got animated, held great eye contact, and was laughing and engaging positively with the "
    "group all afternoon. There were no incidents, safety hazards, or escalated behaviours at all during "
    "the shift. When we wrapped up, his family actually commented on how much his mood had improved since "
    "the morning. Mel even told me, it helped talking about it today, and I liked hanging out at the office. "
    "Overall, it was a highly successful shift. Moving forward, we just need to keep working on those "
    "emotional regulation strategies, particularly around building his resilience to perceived criticism "
    "and processing family frustrations."
)


def _banner(step: str) -> None:
    print("\n" + "=" * 78)
    print(step)
    print("=" * 78)


def main() -> int:
    case_note_id = str(uuid.uuid4())
    worker_id = "worker-test-001"
    client_id = "mel-client-001"

    # Bedrock pipeline calls can be slow; give them room.
    client = httpx.Client(timeout=180.0, auth=AUTH)

    # ── 1. Health ────────────────────────────────────────────────────────────
    _banner("1) GET /health")
    r = client.get(f"{RP}/health")
    print(r.status_code, r.text)
    r.raise_for_status()

    # ── 2. Draft: transcript -> structured case note ─────────────────────────
    _banner("2) POST /draft  (transcript -> structured case note)")
    draft_payload = {
        "transcript": TRANSCRIPT,
        "worker_id": worker_id,
        "client_id": client_id,
        "case_note_id": case_note_id,
        "shift_date": "12 Jun 2026",
        "shift_time": "9:00 AM - 3:00 PM",
        "worker_position": "Support Worker",
    }
    r = client.post(f"{RP}/draft", json=draft_payload)
    print("HTTP", r.status_code)
    if r.status_code >= 400:
        print(r.text)
        return 1
    draft = r.json()
    print(json.dumps(draft, indent=2, ensure_ascii=False))

    # ── 3. Evaluate: structured note -> compliance verdict ───────────────────
    _banner("3) POST /evaluate  (structured note -> RP-detection verdict)")
    eval_payload = {"case_note_id": case_note_id}
    for field in _CARRY_FIELDS:
        if field in draft and draft[field] is not None:
            eval_payload[field] = draft[field]
    # guarantee identity fields even if the draft omitted them
    eval_payload.setdefault("client_id", client_id)
    eval_payload.setdefault("worker_id", worker_id)

    r = client.post(f"{RP}/evaluate", json=eval_payload)
    print("HTTP", r.status_code)
    if r.status_code >= 400:
        print(r.text)
        return 1
    verdict = r.json()
    print(json.dumps(verdict, indent=2, ensure_ascii=False))

    # ── Concise summary line ─────────────────────────────────────────────────
    _banner("RESULT")
    v = verdict.get("verdict", {})
    print(f"Outcome        : {v.get('outcome')}")
    print(f"Risk level     : {v.get('risk_level')}")
    print(f"Alert required : {v.get('alert_required')}")
    print(f"Action         : {v.get('action_required')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPError as exc:
        print(f"\nHTTP error talking to {BASE_URL}: {exc}")
        print("Is the server running?  uvicorn main:create_app --factory --port 8084")
        sys.exit(2)
