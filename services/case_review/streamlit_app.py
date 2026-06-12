"""
Streamlit UI for the restrictive-practice case-review API — a visual version of test.py.

Same flow as test.py:
    1. GET  /v1/restrictive-practices/health     (preflight)
    2. POST /v1/restrictive-practices/draft       (transcript -> structured note)
    3. POST /v1/restrictive-practices/evaluate    (structured note -> RP verdict)

Run it:
    # from services/case_review/ (inside the ai-sena venv)
    streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501

    # then open:  http://3.111.109.14:8501   (server's public IP)

Config (same env vars as test.py — used as UI defaults, all editable in the sidebar):
    SENA_TEST_BASE_URL          default http://localhost:8080/case-review
    SENA_AI_BASIC_AUTH_USER     optional — only if the server enforces basic auth
    SENA_AI_BASIC_AUTH_PASSWORD
"""

import json
import os
import uuid

import httpx
import streamlit as st

# ── Defaults (same env vars as test.py) ───────────────────────────────────
DEFAULT_BASE_URL = os.getenv("SENA_TEST_BASE_URL", "http://localhost:8080/case-review")
DEFAULT_USER = os.getenv("SENA_AI_BASIC_AUTH_USER", "")
DEFAULT_PW = os.getenv("SENA_AI_BASIC_AUTH_PASSWORD", "")

# Fields copied from the /draft output into the /evaluate input — identical to test.py.
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

EXAMPLE_TRANSCRIPT = (
    "I had my shift with Mel today from 9:00am to 3:00pm. When I first arrived, his family "
    "mentioned he'd been pretty frustrated all morning. I noticed right away that he was a bit "
    "more withdrawn and speaking a lot quieter than he usually does. He let me know that he was "
    "feeling upset after getting into an argument with his sibling earlier about his gaming. Even "
    "though he was frustrated, he did a great job staying calm, was very receptive to support, and "
    "was still happy to go ahead with the activities we had planned. We spent a good portion of the "
    "morning focussing on emotional processing. There were no incidents, safety hazards, or escalated "
    "behaviours at all during the shift. Overall, it was a highly successful shift."
)


# ── Page setup ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="SENA Case Review — RP Detection", page_icon="🩺", layout="wide")
st.title("🩺 SENA Case Review — Restrictive-Practice Detection")
st.caption("Enter a shift transcript → the AI drafts a structured case note → then evaluates it for restrictive-practice / compliance risk.")

# ── Sidebar: connection + shift metadata ───────────────────────────────────
with st.sidebar:
    st.header("⚙️ Connection")
    base_url = st.text_input("Base URL", value=DEFAULT_BASE_URL,
                             help="Gateway: http://localhost:8080/case-review  •  Direct: http://127.0.0.1:8084")
    user = st.text_input("Basic auth user (optional)", value=DEFAULT_USER)
    pw = st.text_input("Basic auth password (optional)", value=DEFAULT_PW, type="password")

    st.header("📋 Shift metadata")
    worker_id = st.text_input("Worker ID", value="worker-test-001")
    client_id = st.text_input("Client ID", value="mel-client-001")
    shift_date = st.text_input("Shift date", value="12 Jun 2026")
    shift_time = st.text_input("Shift time", value="9:00 AM - 3:00 PM")
    worker_position = st.text_input("Worker position", value="Support Worker")

base_url = base_url.rstrip("/")
RP = f"{base_url}/v1/restrictive-practices"
auth = (user, pw) if user and pw else None


def _client() -> httpx.Client:
    # Bedrock pipeline calls can be slow; give them room (same 180s as test.py).
    return httpx.Client(timeout=180.0, auth=auth)


# ── Input ──────────────────────────────────────────────────────────────────
transcript = st.text_area("📝 Shift transcript", value=EXAMPLE_TRANSCRIPT, height=240,
                          help="Paste the support-worker's spoken/typed account of the shift.")

run = st.button("▶️  Run draft + evaluate", type="primary", use_container_width=True)

if run:
    if not transcript.strip():
        st.error("Please enter a transcript first.")
        st.stop()

    case_note_id = str(uuid.uuid4())

    # ── 1. Health ──────────────────────────────────────────────────────────
    with st.status("1/3 — Health check…", expanded=False) as status:
        try:
            with _client() as c:
                r = c.get(f"{RP}/health")
            if r.status_code == 200:
                status.update(label=f"1/3 — Health OK ({r.status_code})", state="complete")
            else:
                status.update(label=f"1/3 — Health returned {r.status_code}", state="error")
                st.code(r.text)
                st.stop()
        except Exception as exc:
            status.update(label="1/3 — Cannot reach the API", state="error")
            st.error(f"Connection failed: {exc}\n\nIs the server up and the Base URL correct?")
            st.stop()

    # ── 2. Draft: transcript -> structured note ─────────────────────────────
    with st.status("2/3 — Drafting structured case note (Bedrock)…", expanded=False) as status:
        draft_payload = {
            "transcript": transcript,
            "worker_id": worker_id,
            "client_id": client_id,
            "case_note_id": case_note_id,
            "shift_date": shift_date,
            "shift_time": shift_time,
            "worker_position": worker_position,
        }
        try:
            with _client() as c:
                r = c.post(f"{RP}/draft", json=draft_payload)
        except Exception as exc:
            status.update(label="2/3 — Draft request failed", state="error")
            st.error(f"Request error: {exc}")
            st.stop()
        if r.status_code >= 400:
            status.update(label=f"2/3 — Draft failed ({r.status_code})", state="error")
            st.code(r.text)
            st.stop()
        draft = r.json()
        status.update(label="2/3 — Draft ready ✅", state="complete")

    st.subheader("📄 Structured draft")
    with st.expander("Full draft JSON", expanded=False):
        st.json(draft)

    # ── 3. Evaluate: structured note -> verdict ─────────────────────────────
    with st.status("3/3 — Evaluating for restrictive practices (Bedrock + RAG)…", expanded=False) as status:
        eval_payload = {"case_note_id": case_note_id}
        for field in _CARRY_FIELDS:
            if field in draft and draft[field] is not None:
                eval_payload[field] = draft[field]
        eval_payload.setdefault("client_id", client_id)
        eval_payload.setdefault("worker_id", worker_id)

        try:
            with _client() as c:
                r = c.post(f"{RP}/evaluate", json=eval_payload)
        except Exception as exc:
            status.update(label="3/3 — Evaluate request failed", state="error")
            st.error(f"Request error: {exc}")
            st.stop()
        if r.status_code >= 400:
            status.update(label=f"3/3 — Evaluate failed ({r.status_code})", state="error")
            st.code(r.text)
            st.stop()
        verdict = r.json()
        status.update(label="3/3 — Verdict ready ✅", state="complete")

    # ── Result summary (same fields test.py prints) ─────────────────────────
    st.subheader("⚖️ Verdict")
    v = verdict.get("verdict", verdict) if isinstance(verdict, dict) else {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcome", str(v.get("outcome", "—")))
    c2.metric("Risk level", str(v.get("risk_level", "—")))
    c3.metric("Alert required", str(v.get("alert_required", "—")))
    c4.metric("Action", str(v.get("action_required", "—")))

    with st.expander("Full verdict JSON", expanded=True):
        st.json(verdict)

    st.download_button(
        "⬇️ Download verdict JSON",
        data=json.dumps(verdict, indent=2, ensure_ascii=False),
        file_name=f"verdict_{case_note_id}.json",
        mime="application/json",
    )
