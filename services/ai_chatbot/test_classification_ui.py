"""Streamlit chat UI for the SENA ai_chatbot gateway.

Mirrors the staff UI: login (email/password OR JWT), then chat. Each question
is sent to the gateway, which uses Bedrock to classify it (staff vs policy),
routes it to the right service, and streams the answer back.

Run:
    cd /home/main/SENA/services/ai_chatbot
    streamlit run test_classification_ui.py
"""
import json
import os
import sys

import httpx
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import (
    login_user,
    authenticate_with_jwt,
    get_token,
    get_user_context,
    get_last_error,
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:9000")

st.set_page_config(page_title="SENA Assistant", page_icon="💬")

# Session state init
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "messages" not in st.session_state:
    st.session_state.messages = []


def _ask_gateway(question):
    """Send the question to the gateway, consume the SSE stream, and return
    (answer_text, classification_dict). Yields nothing — collects the full
    response then returns it for display."""
    answer_parts = []
    classification = {}
    routing = {}
    try:
        with httpx.stream(
            "POST",
            f"{GATEWAY_URL}/api/route",
            json={"question": question, "context": {}},
            headers={"Authorization": f"Bearer {get_token()}"},
            timeout=60,
        ) as resp:
            if resp.status_code != 200:
                body = resp.read().decode(errors="replace")
                return f"Gateway error {resp.status_code}: {body}", {}
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                # Only the gateway's meta carries routing/classification; the
                # staff service emits its own meta (session_id only) — ignore it
                # so it can't clobber the real classification.
                if etype == "meta" and event.get("routing"):
                    routing = event["routing"]
                    classification = routing.get("classification", {})
                elif etype == "token":
                    answer_parts.append(event.get("text", ""))
                elif etype == "error":
                    answer_parts.append(f"\n\n⚠️ {event.get('text', 'error')}")
    except httpx.ConnectError:
        return (
            f"Cannot reach the gateway at {GATEWAY_URL}. "
            "Start it with:  python -m uvicorn gateway:app --reload",
            {},
            {},
        )
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}", {}, {}

    return "".join(answer_parts).strip() or "(no response)", classification, routing


# ---- LOGIN ----
if not st.session_state.authenticated:
    st.title("SENA Assistant")

    method = st.radio("Sign in with:", ["Email + Password", "JWT Token"])

    if method == "Email + Password":
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Sign In"):
            with st.spinner("Authenticating..."):
                ok = login_user(email, password)
            if ok:
                st.session_state.authenticated = True
                st.session_state.user_email = email
                st.rerun()
            else:
                st.error(f"Login failed: {get_last_error() or 'Unknown error'}")
    else:
        jwt = st.text_area("Paste JWT token")
        if st.button("Sign In with JWT") and jwt.strip():
            with st.spinner("Validating..."):
                ok = authenticate_with_jwt(jwt.strip())
            if ok:
                st.session_state.authenticated = True
                st.session_state.user_email = "jwt_user"
                st.rerun()
            else:
                st.error(f"JWT validation failed: {get_last_error() or 'Unknown error'}")

    st.stop()


# ---- CHAT ----
st.title("SENA Assistant")
st.caption(f"Logged in as {get_user_context().get('email', st.session_state.get('user_email', '?'))}")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("You:"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            answer, classification, routing = _ask_gateway(prompt)

        targets = routing.get("target_services", [])
        service = classification.get("service", "?")
        confidence = classification.get("confidence", 0)
        reason = classification.get("reason", "")

        if not targets or service == "none":
            st.caption(f"🚫 **Out of scope** — {reason or 'not a staff or policy question.'}")
        else:
            label = " + ".join(t.upper() for t in targets)
            st.caption(f"➡️ Routed to **{label}** ({confidence*100:.0f}% confidence) — {reason}")

        st.write(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})
