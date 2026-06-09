# app/streamlit_app.py
"""
SENA — Chat UI
--------------
Login with org credentials, then chat with the RAG pipeline.
Conversations are logged to JSON by the FastAPI server.

Run:
    streamlit run app/streamlit_app.py
"""
import streamlit as st
import requests
import uuid
import json
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────

API_BASE  = "http://localhost:8000"
APP_TITLE = "SENA"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global styles ──────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Reset Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }
.block-container { padding: 0 !important; max-width: 100% !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #171717;
    border-right: 1px solid #2a2a2a;
    min-width: 240px !important;
    max-width: 260px !important;
}
[data-testid="stSidebar"] * { color: #d4d4d4 !important; }
[data-testid="stSidebar"] .stButton button {
    background: transparent;
    border: none;
    color: #d4d4d4 !important;
    text-align: left;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 13px;
    width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: #262626 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #2a2a2a !important;
    margin: 10px 0 !important;
}

/* ── Login card ── */
.login-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: #0a0a0a;
}
.login-card {
    background: #111111;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 36px 32px;
    width: 100%;
    max-width: 380px;
}
.login-logo {
    font-size: 18px;
    font-weight: 600;
    color: #f5f5f5;
    margin-bottom: 4px;
    letter-spacing: -0.02em;
}
.login-sub {
    font-size: 13px;
    color: #737373;
    margin-bottom: 28px;
}
.login-label {
    font-size: 12px;
    font-weight: 500;
    color: #a3a3a3;
    margin-bottom: 6px;
    letter-spacing: 0.02em;
}
.login-hint {
    font-size: 11px;
    color: #525252;
    margin-top: 5px;
    font-family: monospace;
}
.login-error {
    background: #1c0a0a;
    border: 1px solid #7f1d1d;
    border-radius: 6px;
    padding: 9px 12px;
    font-size: 12.5px;
    color: #fca5a5;
    margin-bottom: 16px;
}

/* ── Chat area ── */
.chat-root {
    display: flex;
    flex-direction: column;
    height: 100vh;
    background: #0a0a0a;
    overflow: hidden;
}

/* message thread */
.msg-thread {
    flex: 1;
    overflow-y: auto;
    padding: 40px 0 20px;
}
.msg-row {
    max-width: 720px;
    margin: 0 auto;
    padding: 6px 24px;
}
.msg-row.user { display: flex; justify-content: flex-end; }
.msg-row.assistant { display: flex; justify-content: flex-start; }

.bubble-user {
    background: #1e3a5f;
    color: #e0effe;
    border-radius: 18px 18px 4px 18px;
    padding: 10px 16px;
    max-width: 75%;
    font-size: 14px;
    line-height: 1.6;
}
.bubble-assistant {
    color: #d4d4d4;
    font-size: 14px;
    line-height: 1.7;
    max-width: 85%;
    padding: 4px 0;
}
.bubble-blocked {
    background: #1c0a0a;
    border-left: 3px solid #ef4444;
    border-radius: 4px 8px 8px 4px;
    padding: 10px 14px;
    color: #fca5a5;
    font-size: 13.5px;
    line-height: 1.6;
    max-width: 85%;
}
.msg-meta {
    font-size: 11px;
    color: #404040;
    margin-top: 6px;
    padding: 0 2px;
}

/* empty state */
.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #404040;
    gap: 8px;
}
.empty-state-title {
    font-size: 20px;
    font-weight: 500;
    color: #525252;
    letter-spacing: -0.02em;
}
.empty-state-sub {
    font-size: 13px;
    color: #404040;
}

/* input bar */
.input-bar {
    padding: 16px 24px 24px;
    background: #0a0a0a;
    max-width: 768px;
    margin: 0 auto;
    width: 100%;
}

/* override streamlit input */
[data-testid="stTextInput"] input {
    background: #171717 !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 10px !important;
    color: #f5f5f5 !important;
    font-size: 14px !important;
    padding: 12px 16px !important;
    caret-color: #f5f5f5 !important;
}
[data-testid="stTextInput"] input:focus {
    border-color: #404040 !important;
    box-shadow: none !important;
}
[data-testid="stTextInput"] input::placeholder {
    color: #525252 !important;
}

/* send button */
.stButton button[kind="primary"] {
    background: #f5f5f5 !important;
    color: #0a0a0a !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    height: 46px !important;
}
.stButton button[kind="primary"]:hover {
    background: #e5e5e5 !important;
}

/* doc type radio in sidebar */
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    font-size: 12px !important;
    color: #a3a3a3 !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {
    font-size: 12px !important;
}

/* user chip in sidebar footer */
.user-chip {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
    color: #a3a3a3 !important;
    margin-top: 12px;
}
.user-chip strong {
    color: #d4d4d4 !important;
    display: block;
    font-size: 13px;
    margin-bottom: 2px;
}

/* blocked banner */
.blocked-banner {
    background: #1c0a0a;
    border: 1px solid #7f1d1d;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    color: #fca5a5;
    margin: 8px 0;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)


# ── Session state ──────────────────────────────────────────────────────────────

def _init():
    defaults = {
        "token":          None,
        "user":           {},         # {user_id, org_id, role, full_name, login_id}
        "messages":       [],         # [{role, content, blocked, sources, label, ts}]
        "session_id":     None,
        "session_title":  None,
        "all_sessions":   [],
        "active_session": None,
        "login_error":    "",
        "doc_type":       "All",      # "All" | "Policy" | "Procedure"
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── Auth helpers ───────────────────────────────────────────────────────────────

def do_login(login_id: str, password: str) -> bool:
    try:
        r = requests.post(
            f"{API_BASE}/auth/login",
            json={"login_id": login_id.strip(), "password": password},
            timeout=10,
        )
        if r.status_code == 401:
            st.session_state.login_error = "Invalid credentials. Please try again."
            return False
        if r.status_code == 403:
            st.session_state.login_error = "This account is inactive."
            return False
        if not r.ok:
            st.session_state.login_error = f"Server error ({r.status_code})."
            return False
        data = r.json()
        st.session_state.token = data["token"]
        st.session_state.user  = {
            "user_id":   data["user_id"],
            "org_id":    data["org_id"],
            "role":      data["role"],
            "full_name": data.get("full_name", ""),
            "login_id":  data.get("login_id", login_id),
        }
        st.session_state.login_error = ""
        return True
    except requests.exceptions.ConnectionError:
        st.session_state.login_error = "Cannot reach server. Is FastAPI running on port 8000?"
        return False
    except Exception as exc:
        st.session_state.login_error = str(exc)
        return False


def logout():
    for k in ["token", "user", "messages", "session_id", "session_title",
              "all_sessions", "active_session", "login_error"]:
        st.session_state[k] = None if k in ("token", "session_id", "session_title", "active_session") else (
            [] if k in ("messages", "all_sessions") else ({} if k == "user" else "")
        )
    st.rerun()


def _headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"}


# ── API helpers ────────────────────────────────────────────────────────────────

def _api_post(endpoint: str, payload: dict):
    try:
        r = requests.post(
            f"{API_BASE}{endpoint}",
            json=payload,
            headers=_headers(),
            timeout=60,
        )
        if r.status_code == 401:
            st.session_state.token = None
            st.rerun()
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach server."
    except Exception as exc:
        return None, str(exc)


def refresh_sessions():
    data, _ = _api_post("/list_sessions", {})
    if data:
        st.session_state.all_sessions = data.get("sessions", [])


def load_session(session_id: str):
    data, err = _api_post("/get_turns", {"session_id": session_id})
    if err or not data:
        return
    msgs = []
    for t in data.get("turns", []):
        msgs.append({"role": "user",      "content": t["question"], "blocked": False,
                     "sources": [], "label": "", "ts": t.get("timestamp", "")})
        msgs.append({"role": "assistant", "content": t["answer"],   "blocked": False,
                     "sources": t.get("sources", []), "label": "", "ts": t.get("timestamp", "")})
    st.session_state.messages       = msgs
    st.session_state.session_id     = session_id
    st.session_state.active_session = session_id


def new_chat():
    new_session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.session_id = new_session_id
    st.session_state.active_session = new_session_id
    st.session_state.session_title = None


# ── Send message (streaming) ───────────────────────────────────────────────────

def send_message(question: str):
    is_new = not st.session_state.messages
    if not st.session_state.session_id:
        st.session_state.session_id = str(uuid.uuid4())

    session_title = st.session_state.session_title or question[:60]
    if not st.session_state.session_title:
        st.session_state.session_title = session_title

    ts = datetime.now().strftime("%H:%M")

    # Append user message immediately
    st.session_state.messages.append({
        "role":    "user",
        "content": question,
        "blocked": False,
        "sources": [],
        "label":   "",
        "ts":      ts,
    })

    payload = {
        "question":      question,
        "session_id":    st.session_state.session_id,
        "session_title": session_title,
        "is_new_chat":   is_new,
    }
    selected_doc_type = st.session_state.get("doc_type", "All")
    if selected_doc_type == "Policy":
        payload["doc_type"] = "policy"
    elif selected_doc_type == "Procedure":
        payload["doc_type"] = "procedure"
    # "All" → omit doc_type so backend returns both

    # Placeholder for streaming tokens
    with st.chat_message("assistant"):
        placeholder = st.empty()

    token_buf    = []
    final_type   = "done"
    final_label  = ""
    final_sources = []
    blocked_text  = None

    try:
        with requests.post(
            f"{API_BASE}/query/stream",
            json=payload,
            headers=_headers(),
            stream=True,
            timeout=120,
        ) as resp:

            if resp.status_code == 401:
                st.session_state.token = None
                st.rerun()
                return

            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue

                event = json.loads(line[5:].strip())
                etype = event.get("type")

                if etype == "meta":
                    final_label   = event.get("label", "")
                    final_sources = event.get("sources", [])

                elif etype == "token":
                    token_buf.append(event["text"])
                    placeholder.markdown("".join(token_buf))

                elif etype == "blocked":
                    final_type   = "blocked"
                    blocked_text = event.get("text", "This question cannot be answered.")
                    final_label  = event.get("label", "BLOCKED")
                    placeholder.markdown(
                        f"<div class='bubble-blocked'>{blocked_text}</div>",
                        unsafe_allow_html=True,
                    )

                elif etype == "error":
                    final_type   = "error"
                    blocked_text = event.get("text", "An error occurred.")
                    placeholder.markdown(
                        f"<div class='bubble-blocked'>{blocked_text}</div>",
                        unsafe_allow_html=True,
                    )

                elif etype == "done":
                    if token_buf:
                        placeholder.markdown("".join(token_buf))

    except requests.exceptions.ConnectionError:
        placeholder.markdown(
            "<div class='bubble-blocked'>Cannot reach server.</div>",
            unsafe_allow_html=True,
        )
        return
    except Exception as exc:
        placeholder.markdown(
            f"<div class='bubble-blocked'>Error: {exc}</div>",
            unsafe_allow_html=True,
        )
        return

    # Commit assistant message to state
    if final_type == "blocked" or final_type == "error":
        st.session_state.messages.append({
            "role":    "assistant",
            "content": blocked_text or "",
            "blocked": True,
            "sources": [],
            "label":   final_label,
            "ts":      datetime.now().strftime("%H:%M"),
        })
    else:
        full_answer = "".join(token_buf)
        st.session_state.messages.append({
            "role":    "assistant",
            "content": full_answer,
            "blocked": False,
            "sources": final_sources,
            "label":   final_label,
            "ts":      datetime.now().strftime("%H:%M"),
        })

    refresh_sessions()
    st.session_state.active_session = st.session_state.session_id

# ── Render a single message ────────────────────────────────────────────────────

def render_message(msg: dict):
    role    = msg["role"]
    content = msg["content"]
    blocked = msg.get("blocked", False)
    sources = msg.get("sources", [])
    label   = msg.get("label", "")
    ts      = msg.get("ts", "")

    if role == "user":
        st.markdown(
            f"<div class='msg-row user'>"
            f"<div class='bubble-user'>{content}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        if blocked:
            st.markdown(
                f"<div class='msg-row assistant'>"
                f"<div class='bubble-blocked'>{content}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            with st.chat_message("assistant"):
                st.markdown(content)
                if sources:
                    src_str = "  ".join(f"`{s}`" for s in sources)
                    st.markdown(
                        f"<div class='msg-meta'>Sources: {src_str}</div>",
                        unsafe_allow_html=True,
                    )


# ════════════════════════════════════════════════════════════════════════════════
# LOGIN PAGE
# ════════════════════════════════════════════════════════════════════════════════

if not st.session_state.token:

    # Centre the form
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)

        st.markdown(
            "<div class='login-logo'>SENA</div>"
            "<div class='login-sub'>Secure knowledge assistant</div>",
            unsafe_allow_html=True,
        )

        if st.session_state.login_error:
            st.markdown(
                f"<div class='login-error'>{st.session_state.login_error}</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div class='login-label'>USER ID</div>", unsafe_allow_html=True)
        login_id = st.text_input(
            "User ID",
            placeholder="org1\\alice.walker",
            label_visibility="collapsed",
            key="input_login_id",
        )
        st.markdown(
            "<div class='login-hint'>Format: orgname\\username</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<div class='login-label'>PASSWORD</div>", unsafe_allow_html=True)
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password",
            label_visibility="collapsed",
            key="input_password",
        )

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Sign in", type="primary", use_container_width=True):
            if not login_id or not password:
                st.session_state.login_error = "Please enter both user ID and password."
                st.rerun()
            else:
                if do_login(login_id, password):
                    new_chat()
                    refresh_sessions()
                    st.rerun()

        st.markdown(
            "<br><div style='text-align:center;font-size:11px;color:#404040'>"
            "Contact your administrator if you need access.</div>",
            unsafe_allow_html=True,
        )

    st.stop()


# ════════════════════════════════════════════════════════════════════════════════
# CHAT PAGE
# ════════════════════════════════════════════════════════════════════════════════

user = st.session_state.user

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        "<div style='font-size:15px;font-weight:600;letter-spacing:-0.02em;"
        "color:#f5f5f5;padding:8px 0 16px'>SENA</div>",
        unsafe_allow_html=True,
    )

    if st.button("+ New chat", use_container_width=True):
        new_chat()
        st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)

    # Session list
    sessions = st.session_state.all_sessions
    if sessions:
        st.markdown(
            "<div style='font-size:10px;color:#525252;letter-spacing:0.08em;"
            "text-transform:uppercase;padding:0 2px 6px'>Recent</div>",
            unsafe_allow_html=True,
        )
        for sess in (sessions[-30:]):  # most recent at top
            sid   = sess.get("session_id") or sess.get("id", "")
            title = sess.get("title") or sess.get("first_question", "Chat")[:40]
            is_active = sid == st.session_state.active_session
            label = ("-> " if is_active else "") + title
            if st.button(label, key=f"sess_{sid}", use_container_width=True):
                load_session(sid)
                st.rerun()
    else:
        st.markdown(
            "<div style='font-size:12px;color:#404040;padding:4px 2px'>No conversations yet.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr>", unsafe_allow_html=True)

    # Doc type filter
    st.markdown(
        "<div style='font-size:10px;color:#525252;letter-spacing:0.08em;"
        "text-transform:uppercase;padding:0 2px 6px'>Filter by type</div>",
        unsafe_allow_html=True,
    )
    st.session_state.doc_type = st.radio(
        "Document type",
        options=["All", "Policy", "Procedure"],
        index=["All", "Policy", "Procedure"].index(st.session_state.get("doc_type", "All")),
        label_visibility="collapsed",
        horizontal=True,
    )

    st.markdown("<hr>", unsafe_allow_html=True)

    # User info + logout
    st.markdown(
        f"<div class='user-chip'>"
        f"<strong>{user.get('full_name') or user.get('login_id','')}</strong>"
        f"{user.get('org_id','')} &middot; {user.get('role','')}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Sign out", use_container_width=True):
        logout()


# ── Main chat area ─────────────────────────────────────────────────────────────

messages = st.session_state.messages

if not messages:
    st.markdown("<br>" * 6, unsafe_allow_html=True)
    name_part = user.get("full_name", "").split()[0] if user.get("full_name") else ""
    greeting  = f"Hello, {name_part}" if name_part else "Hello"
    st.markdown(
        f"<div style='text-align:center'>"
        f"<div style='font-size:24px;font-weight:500;color:#525252;"
        f"letter-spacing:-0.03em;margin-bottom:8px'>{greeting}</div>"
        f"<div style='font-size:14px;color:#404040'>How can I help you today?</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<br>" * 4, unsafe_allow_html=True)
else:
    for msg in messages:
        render_message(msg)


# ── Chat Input ────────────────────────────────────────────────────────────────

question = st.chat_input("Ask a question...")

if question and question.strip():
    send_message(question.strip())
    st.rerun()