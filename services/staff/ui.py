"""Simple Streamlit chat UI for the SENA NDIS assistant.

Mirrors the terminal experience: login (email/password OR JWT), then chat.
No sidebar, no debug logs, no fancy controls.

Run:
    cd /home/main/SENA/services/staff
    streamlit run ui.py
"""
import io
import os
import sys
from contextlib import redirect_stdout, redirect_stderr

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from state import user_context
from auth import login_user, authenticate_user, authenticate_with_jwt
from router import process_query


st.set_page_config(page_title="SENA Assistant", page_icon="💬")

# Session state init
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "messages" not in st.session_state:
    st.session_state.messages = []


def _run_query(question):
    """Call process_query and return the response text."""
    out_buf, err_buf = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            result = process_query(question)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"

    if isinstance(result, str) and result.strip():
        return result.strip()

    # Fallback: extract from captured stdout
    captured = out_buf.getvalue()
    if "Sena:" in captured:
        return captured.split("Sena:", 1)[-1].strip()
    return captured.strip() or "(no response)"


# ---- LOGIN ----
if not st.session_state.authenticated:
    st.title("SENA Assistant")

    method = st.radio("Sign in with:", ["Email + Password", "JWT Token"])

    if method == "Email + Password":
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Sign In"):
            with st.spinner("Authenticating..."):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    ok = login_user(email, password) and authenticate_user()
            if ok:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Login failed.")
    else:
        jwt = st.text_area("Paste JWT token")
        if st.button("Sign In with JWT") and jwt.strip():
            with st.spinner("Validating..."):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    ok = authenticate_with_jwt(jwt.strip())
            if ok:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("JWT validation failed.")

    st.stop()


# ---- CHAT ----
st.title("SENA Assistant")
st.caption(f"Logged in as {user_context.get('email', '?')}")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("You:"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = _run_query(prompt)
        st.write(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
