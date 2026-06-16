"""Streamlit wrapper that serves the case-review **Draft demo** (draft_demo.html).

draft_demo.html was written to be served *same-origin* by the FastAPI app — its
`fetch()` calls use root-relative paths like `/v1/restrictive-practices/draft`.
Streamlit renders it inside a sandboxed iframe (a different origin), so we rewrite
those paths to an absolute, **browser-reachable** API base. The case-review service
must allow CORS for these cross-origin calls (CORSMiddleware in main.py).

Run:
    streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501 \
        --server.headless true --server.baseUrlPath case-review-ui
"""
import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="SENA Case Note Drafter", page_icon="📝", layout="wide")

# Public, BROWSER-reachable base URL for the case-review API. The embedded HTML's
# fetch() runs in the user's browser, so this must be a PUBLIC URL — NOT the
# docker-internal hostname. Through nginx, <host>/case-review strips to the app.
DEFAULT_API_BASE = os.getenv("SENA_PUBLIC_API_BASE", "https://dev-api.isena.org/case-review")

with st.sidebar:
    st.header("⚙️ API base")
    api_base = st.text_input(
        "Case-review API base (browser-reachable)",
        value=DEFAULT_API_BASE,
        help="Where the demo's fetch() calls go — must be reachable from YOUR browser. "
             "e.g. https://dev-api.isena.org/case-review  or  http://<ip>:8080/case-review",
    ).rstrip("/")

# draft_demo.html lives next to this file in the image (COPYed in the Dockerfile).
html = Path(__file__).with_name("draft_demo.html").read_text(encoding="utf-8")

# The demo uses root-relative API paths (same-origin design). Rewrite every
# `'/v1/...'` / `"/v1/..."` to the absolute public base so the iframe's
# cross-origin fetch reaches the API through nginx.
html = html.replace("'/v1/", f"'{api_base}/v1/").replace('"/v1/', f'"{api_base}/v1/')

components.html(html, height=1600, scrolling=True)
