"""Configuration for the ai_chatbot gateway.

All values are env-overridable so nothing (ports, paths) is hardcoded in logic.
The gateway fronts two existing Streamlit apps + the policy FastAPI, embedding
them in one shell under a single origin.
"""
import os
import sys
from pathlib import Path

# ---- Paths ----
# this file lives in services/ai_chatbot/, so services/ is one level up.
_THIS_DIR = Path(__file__).resolve().parent
SERVICES_DIR = _THIS_DIR.parent
REPO_ROOT = SERVICES_DIR.parent   # /home/main/SENA — needed on PYTHONPATH for policy imports

STAFF_DIR = Path(os.getenv("STAFF_DIR", SERVICES_DIR / "staff"))
POLICY_DIR = Path(os.getenv("POLICY_DIR", SERVICES_DIR / "policy_proc"))

LOGS_DIR = Path(os.getenv("LOGS_DIR", _THIS_DIR / "logs"))

# ---- Ports / bind ----
HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")          # gateway public bind
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "9000"))

# Children bind to loopback only — they're reachable solely via the gateway proxy.
CHILD_HOST = os.getenv("CHILD_HOST", "127.0.0.1")
# Non-default ports so we don't collide with manually-run Streamlit apps (8501/8502).
STAFF_PORT = int(os.getenv("STAFF_PORT", "8601"))
POLICY_PORT = int(os.getenv("POLICY_PORT", "8602"))
# Policy Streamlit hardcodes the API at localhost:8000, so this one is fixed.
POLICY_API_PORT = int(os.getenv("POLICY_API_PORT", "8000"))

# ---- Behaviour ----
# When true the gateway spawns/stops the child processes itself (one-command UX).
# Set false if you run the children separately; the gateway then only proxies.
MANAGE_CHILDREN = os.getenv("MANAGE_CHILDREN", "true").lower() in ("1", "true", "yes")

# How long to wait (seconds) for each child to report healthy at startup.
CHILD_HEALTH_TIMEOUT = float(os.getenv("CHILD_HEALTH_TIMEOUT", "60"))

# ---- Mount prefixes (must match each child's --server.baseUrlPath) ----
STAFF_PREFIX = "staff"
POLICY_PREFIX = "policy"

# Upstream origins the proxy targets (path is preserved unchanged).
STAFF_ORIGIN = f"http://{CHILD_HOST}:{STAFF_PORT}"
POLICY_ORIGIN = f"http://{CHILD_HOST}:{POLICY_PORT}"
STAFF_WS_ORIGIN = f"ws://{CHILD_HOST}:{STAFF_PORT}"
POLICY_WS_ORIGIN = f"ws://{CHILD_HOST}:{POLICY_PORT}"


def _streamlit_cmd(entry: str, port: int, base_url_path: str) -> list[str]:
    """Build a Streamlit launch command tuned for same-origin iframe embedding."""
    return [
        sys.executable, "-m", "streamlit", "run", entry,
        "--server.address", CHILD_HOST,
        "--server.port", str(port),
        "--server.baseUrlPath", base_url_path,
        "--server.headless", "true",
        "--server.enableXsrfProtection", "false",
        "--server.enableCORS", "false",
        "--browser.gatherUsageStats", "false",
    ]


# Each child: (name, argv, cwd, health_url).
def child_specs() -> list[dict]:
    specs = [
        {
            "name": "policy_api",
            "argv": [
                sys.executable, "-m", "uvicorn", "app.main:app",
                "--host", CHILD_HOST, "--port", str(POLICY_API_PORT),
            ],
            "cwd": str(POLICY_DIR),
            # pipeline.py uses repo-root-absolute imports (services.policy_proc.*)
            "env": {"PYTHONPATH": str(REPO_ROOT)},
            "health_url": f"http://{CHILD_HOST}:{POLICY_API_PORT}/health",
        },
        {
            "name": "staff_api",
            "argv": [
                sys.executable, "-m", "uvicorn", "api_main:app",
                "--host", CHILD_HOST, "--port", str(STAFF_PORT),
            ],
            "cwd": str(STAFF_DIR),
            "env": {"PYTHONPATH": str(REPO_ROOT)},
            "health_url": f"http://{CHILD_HOST}:{STAFF_PORT}/health",
        },
    ]
    return specs
