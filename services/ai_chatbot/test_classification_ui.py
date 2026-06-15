"""SENA Assistant — test UI matching production design.

Light theme, clean layout: input box at top, chips below, chat history.
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

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")

# Two independent logins, picked per chip:
#   • Staff & Client  → the ISENA email login (nexaxody@…), entered on the sign-in screen.
#   • Policy & Proc   → the policy service's own fake_users.json login, because that
#                       org scoping (e.g. org_sunrise) is what has policy docs ingested.
# The UI therefore holds TWO bearer tokens and sends the right one to the gateway.
POLICY_LOGIN_URL = os.getenv("POLICY_LOGIN_URL", "http://localhost:8080/policy/auth/login")
POLICY_FAKE_LOGIN_ID = os.getenv("POLICY_FAKE_LOGIN_ID", "sunrise\\alice.walker")
POLICY_FAKE_PASSWORD = os.getenv("POLICY_FAKE_PASSWORD", "Test@1234")
POLICY_CATEGORIES = {"policy", "procedure"}

# Chip label → category key the gateway understands
CHIPS = [
    ("Policies", "policy"),
    ("Check Shifts", "shifts"),
    ("Procedures", "procedure"),
    ("Client's information", "client"),
]

st.set_page_config(
    page_title="SENA Assistant",
    page_icon="💬",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Dark theme with improved layout
st.markdown(
    """
    <style>
    .stButton>button { border-radius: 8px; }
    .stButton>button:hover { opacity: 0.8; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_chip" not in st.session_state:
    st.session_state.active_chip = None


def get_policy_token():
    """Lazily sign in to the policy service with fake_users.json creds; cache in session."""
    tok = st.session_state.get("policy_token")
    if tok:
        return tok
    try:
        resp = httpx.post(
            POLICY_LOGIN_URL,
            json={"login_id": POLICY_FAKE_LOGIN_ID, "password": POLICY_FAKE_PASSWORD},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            tok = (data.get("token") or data.get("access_token")) if isinstance(data, dict) else data
            if tok:
                st.session_state.policy_token = tok
                return tok
            st.session_state.policy_login_error = f"no token in response: {data}"
        else:
            st.session_state.policy_login_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        st.session_state.policy_login_error = f"{type(e).__name__}: {e}"
    return None


def ask_gateway(question, category=None):
    """POST to the gateway, consume the SSE stream.

    Token is chosen by chip: policy/procedure use the fake_users token, everything
    else (staff/client) uses the ISENA email-login token.
    """
    answer, classification, routing = [], {}, {}
    context = {"category": category} if category else {}

    if category in POLICY_CATEGORIES:
        token = get_policy_token()
        if not token:
            err = st.session_state.get("policy_login_error", "unknown error")
            return (
                f"Couldn't sign in to the policy service as {POLICY_FAKE_LOGIN_ID} "
                f"via {POLICY_LOGIN_URL} — {err}",
                {}, {},
            )
    else:
        token = get_token()

    try:
        with httpx.stream(
            "POST",
            f"{GATEWAY_URL}/ai-chatbot/route",
            json={"question": question or "", "context": context},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        ) as resp:
            if resp.status_code != 200:
                return (
                    f"Gateway error {resp.status_code}: {resp.read().decode(errors='replace')}",
                    {},
                    {},
                )
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    line, buf = buf.split("\n\n", 1)
                    if not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    t = ev.get("type")
                    if t == "meta" and ev.get("routing"):
                        routing = ev["routing"]
                        classification = routing.get("classification", {})
                    elif t == "token":
                        answer.append(ev.get("text", ""))
                    elif t == "error":
                        answer.append(f"\n\n⚠️ {ev.get('text', 'error')}")
    except httpx.ConnectError:
        return (
            f"Cannot reach the gateway at {GATEWAY_URL}. Start it: python gateway.py",
            {},
            {},
        )
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}", {}, {}
    return "".join(answer).strip() or "(no response)", classification, routing


def send(question, category=None):
    """Run one turn and append to chat history.

    - category set + no question  → bare chip tap (uses section seed question)
    - category set + question      → scoped question within that section
    - no category + question       → free-text, Bedrock classifies
    """
    # Display the typed question, or the section name for a bare chip tap.
    if question:
        label = question
    elif category:
        label = next((lbl for lbl, c in CHIPS if c == category), category.title())
    else:
        label = ""

    st.session_state.messages.append(
        {"role": "user", "content": label, "category": category if not question else None}
    )
    answer, classification, routing = ask_gateway(question, category)
    targets = routing.get("target_services", [])
    service = classification.get("service", "?")
    reason = classification.get("reason", "")
    conf = classification.get("confidence", 0)

    if not targets or service == "none":
        caption = f"❌ Out of scope — {reason or 'not a staff or policy question.'}"
    else:
        names = " + ".join("policy_proc" if t == "policy" else t for t in targets)
        caption = f"✓ Routed to **{names}** ({conf*100:.0f}%)"

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "caption": caption}
    )


# ── LOGIN ───────────────────────────────────────────────────────────────────────
if not st.session_state.authenticated:
    st.title("SENA Assistant")
    method = st.radio("Sign in with:", ["Email + Password", "JWT Token"], label_visibility="collapsed")
    if method == "Email + Password":
        st.caption("This logs in **Staff & Client**. **Policies & Procedures** auto-sign-in "
                   "with the policy fake_users account in the background.")
        email = st.text_input("Email", value="nexaxody@mailinator.com")
        password = st.text_input("Password", type="password", value="Test@1234")
        if st.button("Sign In", type="primary", use_container_width=True):
            with st.spinner("Authenticating..."):
                ok = login_user(email, password)
            if ok:
                st.session_state.authenticated = True
                st.session_state.user_email = email
                st.rerun()
            else:
                st.error(f"Login failed: {get_last_error() or 'Unknown error'}")
    else:
        jwt = st.text_area("Paste JWT token", height=100)
        if st.button("Sign In with JWT", type="primary", use_container_width=True):
            with st.spinner("Validating..."):
                ok = authenticate_with_jwt(jwt.strip())
            if ok:
                st.session_state.authenticated = True
                st.session_state.user_email = "jwt_user"
                st.rerun()
            else:
                st.error(f"JWT validation failed: {get_last_error() or 'Unknown error'}")
    st.stop()


# ── CHAT ──────────────────────────────────────────────────────────────────────
col1, col2 = st.columns([4, 1])
col1.title("SENA Assistant")
if col2.button("Logout", use_container_width=True):
    st.session_state.authenticated = False
    st.session_state.messages = []
    st.rerun()

st.caption(f"Logged in as {get_user_context().get('email', st.session_state.get('user_email', '?'))}")

# Chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("caption"):
            st.caption(msg["caption"])
        if msg["role"] == "user" and msg.get("category"):
            category_label = next((label for label, cat in CHIPS if cat == msg["category"]), msg["category"].title())
            st.write(f"**{category_label}**")
        else:
            st.write(msg["content"])

# Show active section pill (inline, in the chat flow)
if st.session_state.active_chip:
    chip_label = next((label for label, cat in CHIPS if cat == st.session_state.active_chip), st.session_state.active_chip.title())
    c1, c2 = st.columns([5, 1])
    c1.markdown(f"📌 Section: **{chip_label}** — ask your question below")
    if c2.button("✕ Clear", use_container_width=True):
        st.session_state.active_chip = None
        st.rerun()

st.divider()

# ── INLINE INPUT BOX (in content flow, not floating) ──────────────────────────
placeholder = (
    f"Ask about {st.session_state.active_chip}..."
    if st.session_state.active_chip
    else "Ask me anything..."
)
with st.form(key="ask_form", clear_on_submit=True):
    prompt = st.text_area("Question", placeholder=placeholder,
                          label_visibility="collapsed", height=80)
    submitted = st.form_submit_button("↑  Send", type="primary", use_container_width=True)
    if submitted and prompt.strip():
        with st.spinner("Thinking..."):
            # If a section is active, route scoped to it; else free-text classify.
            send(prompt.strip(), st.session_state.active_chip)
        st.rerun()

# ── CHIPS (right below the input, like the mockup) ────────────────────────────
cols = st.columns(len(CHIPS))
for col, (label, category) in zip(cols, CHIPS):
    is_active = category == st.session_state.active_chip
    if col.button(("● " if is_active else "") + label,
                  use_container_width=True, key=f"chip_{category}"):
        st.session_state.active_chip = category
        st.rerun()
