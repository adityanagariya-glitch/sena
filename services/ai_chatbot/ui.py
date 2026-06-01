"""Simple Streamlit chat UI for testing SENA ai_chatbot gateway.

This mirrors the staff UI but routes through the gateway service orchestrator
instead of calling staff services directly.

Run:
    cd /home/main/SENA/services/ai_chatbot
    streamlit run ui.py --server.baseUrlPath staff
"""
import io
import os
import sys
import json
import asyncio
from contextlib import redirect_stdout, redirect_stderr

import streamlit as st
import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# For testing: hardcoded test users (replace with real auth in production)
TEST_USERS = {
    "test@example.com": {"password": "password", "user_id": "user123", "org_id": "org456"},
    "admin@example.com": {"password": "admin", "user_id": "admin1", "org_id": "org456"},
}

TEST_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoidGVzdF91c2VyIiwib3JnX2lkIjoib3JnMTIzIiwicm9sZSI6InN0YWZmIiwiaWF0IjoxNjc3NTk5NjAwfQ.test"

st.set_page_config(page_title="SENA Assistant", page_icon="💬")

# Session state init
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_context" not in st.session_state:
    st.session_state.user_context = {}
if "jwt_token" not in st.session_state:
    st.session_state.jwt_token = None


async def _call_gateway_streaming(question: str, jwt_token: str) -> str:
    """Call the gateway /route endpoint and stream the response."""
    gateway_url = os.getenv("GATEWAY_URL", "http://localhost:9000")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{gateway_url}/api/route",
                json={
                    "question": question,
                    "context": st.session_state.user_context,
                },
                headers={"Authorization": f"Bearer {jwt_token}"},
            ) as response:
                full_response = ""
                placeholder = st.empty()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            event = json.loads(line[6:])
                            if event.get("type") == "token":
                                token_text = event.get("text", "")
                                full_response += token_text
                                placeholder.markdown(full_response)
                        except json.JSONDecodeError:
                            pass

                return full_response or "(no response)"
    except asyncio.TimeoutError:
        return "Error: Request timeout (gateway may be unavailable)"
    except httpx.ConnectError:
        return f"Error: Cannot connect to gateway at {gateway_url}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


def _run_query(question: str) -> str:
    """Run query through gateway."""
    if not st.session_state.jwt_token:
        return "Error: Not authenticated"

    try:
        # Use asyncio to run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_call_gateway_streaming(question, st.session_state.jwt_token))
        loop.close()
        return result
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ---- LOGIN ----
if not st.session_state.authenticated:
    st.title("SENA Assistant")
    st.write("Test the ai_chatbot gateway")

    method = st.radio("Sign in with:", ["Email + Password", "JWT Token"])

    if method == "Email + Password":
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Sign In"):
            if email in TEST_USERS and TEST_USERS[email]["password"] == password:
                user = TEST_USERS[email]
                st.session_state.authenticated = True
                st.session_state.user_context = {
                    "email": email,
                    "user_id": user["user_id"],
                    "org_id": user["org_id"],
                }
                # Generate a simple JWT (in production, use proper JWT signing)
                st.session_state.jwt_token = TEST_JWT
                st.success(f"Logged in as {email}")
                st.rerun()
            else:
                st.error("Login failed. Try test@example.com / password")
    else:
        jwt = st.text_area("Paste JWT token (or use default test token)")
        if st.button("Sign In with JWT"):
            token = jwt.strip() or TEST_JWT
            # In production, validate the JWT signature
            st.session_state.authenticated = True
            st.session_state.user_context = {
                "email": "test@example.com",
                "user_id": "test_user",
                "org_id": "org123",
            }
            st.session_state.jwt_token = token
            st.success("Logged in with JWT")
            st.rerun()

    st.stop()


# ---- CHAT ----
st.title("SENA Assistant")
st.caption(f"Logged in as {st.session_state.user_context.get('email', '?')}")

# Show gateway info
gateway_url = os.getenv("GATEWAY_URL", "http://localhost:9000")
st.info(f"🔗 Connected to gateway: {gateway_url}")

# Display messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Chat input
if prompt := st.chat_input("You:"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking (routing & streaming from gateway)..."):
            response = _run_query(prompt)
        st.write(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

# Debug info in sidebar
with st.sidebar:
    st.write("### Debug Info")
    st.write(f"**Authenticated**: {st.session_state.authenticated}")
    st.write(f"**User ID**: {st.session_state.user_context.get('user_id', 'N/A')}")
    st.write(f"**Gateway**: {gateway_url}")

    if st.button("Logout"):
        st.session_state.authenticated = False
        st.session_state.messages = []
        st.session_state.jwt_token = None
        st.rerun()
