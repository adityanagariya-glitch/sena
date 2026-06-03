"""Streamlit UI for the case-note monthly-summary service.

Mirrors services/staff/ui.py: login (email/password OR JWT), then choose which
summary to run (Org register roll-up / Mobile content summary) and see the result.
Everything is also logged to the terminal that launched Streamlit.

Run:
    cd /home/main/SENA/services/casenote_monthly
    /home/main/SENA/sena-ai/bin/python -m streamlit run ui.py
"""
import calendar
import os
import sys
import time

import requests
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException

from auth import validate_jwt, decode_jwt
import org_api
import mobile_api

BACKEND = "https://dev-api.isena.org/api"
_BACKEND_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://dev-api.isena.org",
    "Referer": "https://dev-api.isena.org/",
}

# ---- terminal logging (always to the real terminal, never swallowed) ----
_TERM = sys.__stdout__


def term(msg: str) -> None:
    """Log to the launching terminal with a timestamp."""
    print(f"[ui {time.strftime('%H:%M:%S')}] {msg}", file=_TERM, flush=True)


def backend_login(email: str, password: str) -> tuple[str | None, str | None, str | None]:
    """POST /auth/ai/login → (token, org_id, member_id). Returns (None, ...) on failure."""
    term(f"login attempt: {email}")
    try:
        resp = requests.post(f"{BACKEND}/auth/ai/login",
                             json={"email": email, "password": password},
                             headers=_BACKEND_HEADERS, timeout=20)
    except requests.RequestException as e:
        term(f"login error: {e}")
        return None, None, None
    if resp.status_code != 200:
        term(f"login failed: HTTP {resp.status_code} — {resp.text[:200]}")
        return None, None, None
    data = resp.json().get("data", {})
    token = data.get("accessToken") or data.get("access_token") or data.get("token")
    membership = (data.get("user", {}).get("organizationMembership") or [{}])[0]
    org_id = (membership.get("organization") or {}).get("id") or \
        (data.get("defaultContext") or {}).get("organizationId")
    member_id = membership.get("id")
    term(f"login ok: org={org_id} member={member_id}")
    return token, org_id, member_id


def run_summary(which: str, token: str, org_id: str, member_id: str, month: int, year: int):
    """Call the in-process summary builder for the chosen app. Returns the response model."""
    app = org_api if which == "org" else mobile_api
    req = app.MonthlySummaryRequest(
        organizationId=org_id, memberId=member_id, month=month, year=year)
    term(f"running {which.upper()} summary — org={org_id} member={member_id} {year}-{month:02d}")
    t0 = time.time()
    result = app._build_summary(token, req)   # sync; prints client/bedrock logs to terminal
    term(f"{which.upper()} summary done in {time.time() - t0:.1f}s — "
         f"mode={result.mode} "
         f"{'notes=' + str(result.noteCount) if which == 'mobile' else 'shifts=' + str(result.shiftCount)}")
    return result


# ──────────────────────────── page ────────────────────────────
st.set_page_config(page_title="Case-Note Monthly Summary", page_icon="🗂️")

for key, default in (("token", ""), ("org_id", ""), ("member_id", "")):
    if key not in st.session_state:
        st.session_state[key] = default

# ---- LOGIN ----
if not st.session_state.token:
    st.title("Case-Note Monthly Summary")
    method = st.radio("Sign in with:", ["Email + Password", "JWT Token"])

    if method == "Email + Password":
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Sign In"):
            with st.spinner("Authenticating..."):
                token, org_id, member_id = backend_login(email, password)
            if token:
                st.session_state.token = token
                st.session_state.org_id = org_id or ""
                st.session_state.member_id = member_id or ""
                st.rerun()
            else:
                st.error("Login failed — check the terminal for details.")
    else:
        jwt = st.text_area("Paste JWT token")
        if st.button("Sign In with JWT") and jwt.strip():
            ok, err, claims = validate_jwt(jwt.strip())
            if ok:
                st.session_state.token = jwt.strip()
                claims = claims or {}
                st.session_state.org_id = claims.get("organizationId", "") or ""
                st.session_state.member_id = claims.get("memberId", "") or ""
                term("JWT accepted")
                st.rerun()
            else:
                term(f"JWT rejected: {err}")
                st.error(f"JWT validation failed: {err}")

    st.stop()


# ---- AUTHENTICATED: choose + run ----
st.title("Case-Note Monthly Summary")
claims = decode_jwt(st.session_state.token) or {}
st.caption(f"Signed in — {claims.get('email', 'token loaded')}")
if st.button("Sign out"):
    for k in ("token", "org_id", "member_id"):
        st.session_state[k] = ""
    st.rerun()

st.subheader("Parameters")
org_id = st.text_input("Organization ID", value=st.session_state.org_id)
member_id = st.text_input("Member ID", value=st.session_state.member_id)
col_m, col_y = st.columns(2)
month = col_m.selectbox("Month", list(range(1, 13)),
                        format_func=lambda m: f"{m:02d} — {calendar.month_name[m]}")
year = col_y.number_input("Year", min_value=2000, max_value=2100, value=2026, step=1)

st.subheader("Which summary?")
st.caption("**Org** = admin/owner token → register status roll-up (metadata). "
           "**Mobile** = support-worker token → real note-content summary.")
c1, c2 = st.columns(2)
run_org = c1.button("▶ Run Org summary", use_container_width=True)
run_mobile = c2.button("▶ Run Mobile summary", use_container_width=True)

which = "org" if run_org else "mobile" if run_mobile else None

if which:
    if not org_id or not member_id:
        st.error("Organization ID and Member ID are required.")
        st.stop()
    with st.spinner(f"Running {which} summary…"):
        try:
            result = run_summary(which, st.session_state.token,
                                 org_id, member_id, int(month), int(year))
        except HTTPException as e:
            term(f"{which.upper()} summary HTTP {e.status_code}: {e.detail}")
            st.error(f"HTTP {e.status_code}: {e.detail}")
            st.stop()
        except Exception as e:
            term(f"{which.upper()} summary error: {type(e).__name__}: {e}")
            st.error(f"{type(e).__name__}: {e}")
            st.stop()

    data = result.model_dump()
    summary = data.pop("summary", "")

    st.success(f"Done — mode: {data.get('mode')}")
    # counts as metrics
    metric_keys = [k for k in data if isinstance(data[k], int)]
    if metric_keys:
        cols = st.columns(len(metric_keys))
        for col, k in zip(cols, metric_keys):
            col.metric(k, data[k])
    with st.expander("Raw response", expanded=False):
        st.json(data)

    st.subheader("Summary")
    st.markdown(summary)
    term("summary rendered in UI")
