"""
Test script for SENA AI Chatbot Gateway — tests all sections and chips.

Uses Docker Compose configuration (services/docker-compose.deploy.yml).

Usage:
    python test_gateway.py [--local]

Options:
    --local     Run tests against localhost (dev mode)
    --policy-dev-auth
                Test policy_proc's internal fake_users.json login directly.
                By default policy/procedure use the gateway ISENA bearer token.
    (default)   Run tests against docker services

Credentials:
    Staff/Client (email login):
        Email: nexaxody@mailinator.com
        Password: Test@1234

    Policy/Procedure (fake_users.json):
        Login ID: sunrise\\alice.walker
        Password: Test@1234
"""
import sys
import os
import json
import httpx
import logging
import socket

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# Detect if we're in Docker or on host
def is_in_docker():
    """Check if running inside a Docker container."""
    return os.path.exists('/.dockerenv')

def can_reach_localhost(port):
    """Check if we can reach localhost on a specific port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def gateway_is_healthy(base_url):
    """Check the gateway health endpoint, not just whether a port is open."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/healthz", timeout=3)
        if resp.status_code != 200:
            return False
        return resp.json().get("gateway") is True
    except Exception:
        return False

# Docker configuration from docker-compose.deploy.yml
DOCKER_CONFIG = {
    "reverse_proxy": "http://sena-reverse-proxy-internal:80",  # Internal to docker
    "ai_chatbot": "http://sena-ai-chatbot-internal:8003",      # Internal to docker
    "policy": "http://sena-policy-proc-internal:8000",         # Policy child process
    "staff": "http://sena-staff-internal:8001",                 # Staff child process
}

# Localhost configuration (for dev on host)
LOCALHOST_CONFIG = {
    "gateway_reverse_proxy": "http://localhost:8080/ai-chatbot",  # Via nginx
    "gateway_direct": "http://localhost:8003",                    # Direct to ai-chatbot
    "policy_auth": "http://localhost:8000/auth/login",            # Policy internal
    "staff_auth": "http://localhost:8001",                        # Staff internal
}

# Determine configuration
if "--local" in sys.argv or not is_in_docker():
    logger.info("🖥️  Running in LOCAL mode (host machine)")
    # Try to detect which endpoint is available. Port 8080 can be open even when
    # nginx is serving Certbot's fallback 404, so probe /healthz through the
    # chatbot prefix before selecting it.
    if gateway_is_healthy(LOCALHOST_CONFIG["gateway_reverse_proxy"]):
        GATEWAY_URL = LOCALHOST_CONFIG["gateway_reverse_proxy"]
        POLICY_AUTH_URL = LOCALHOST_CONFIG["policy_auth"]
        logger.info(f"   Using reverse proxy: {GATEWAY_URL}")
    elif gateway_is_healthy(LOCALHOST_CONFIG["gateway_direct"]):
        GATEWAY_URL = LOCALHOST_CONFIG["gateway_direct"]
        POLICY_AUTH_URL = LOCALHOST_CONFIG["policy_auth"]
        logger.info(f"   Using direct ai-chatbot: {GATEWAY_URL}")
    else:
        if can_reach_localhost(8080):
            logger.error("❌ nginx is reachable on localhost:8080, but /ai-chatbot/healthz is not.")
            logger.error("   Recreate/reload the reverse proxy so services/nginx/dev-api.isena.org.conf is mounted.")
        logger.error("❌ Cannot reach ai-chatbot. Make sure containers are running:")
        logger.error("   docker compose -f services/docker-compose.deploy.yml up -d")
        sys.exit(1)
else:
    logger.info("🐳 Running in DOCKER mode (inside container)")
    GATEWAY_URL = DOCKER_CONFIG["ai_chatbot"]
    POLICY_AUTH_URL = DOCKER_CONFIG["policy"] + "/auth/login"
    logger.info(f"   Using Docker network: {GATEWAY_URL}")

# Allow override via environment variable
GATEWAY_URL = os.getenv("GATEWAY_URL", GATEWAY_URL)
POLICY_AUTH_URL = os.getenv("POLICY_AUTH_URL", POLICY_AUTH_URL)
USE_POLICY_DEV_AUTH = (
    "--policy-dev-auth" in sys.argv
    or os.getenv("USE_POLICY_DEV_AUTH", "").lower() in ("1", "true", "yes")
)

# Auth service URL (for staff/client login) — always hits the real API
AUTH_URL = "https://dev-api.isena.org/api/auth/ai/login"

# Test data
STAFF_CLIENT_CREDS = {
    "email": "nexaxody@mailinator.com",
    "password": "Test@1234",
}

POLICY_PROC_CREDS = {
    "login_id": "sunrise\\alice.walker",
    "password": "Test@1234",
}

# Test questions for each chip
QUESTIONS = {
    "shifts": "What are my shifts this week?",
    "client": "Who are my clients?",
    "policy": "What is the leave policy?",
    "procedure": "What should I do if there's a safety incident?",
}

def get_staff_client_token():
    """Get token for staff/client sections using email login."""
    logger.info("🔐 Authenticating staff/client (email login)...")
    try:
        resp = httpx.post(
            AUTH_URL,
            json=STAFF_CLIENT_CREDS,
            timeout=15,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://dev-api.isena.org",
                "Referer": "https://dev-api.isena.org/",
            },
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            token = data.get("accessToken") or data.get("access_token") or data.get("token")
            if token:
                logger.info(f"✅ Staff/Client token obtained")
                return token
            else:
                logger.error(f"❌ No token in response: {data}")
                return None
        else:
            logger.error(f"❌ Auth failed {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"❌ Auth error: {e}")
        return None

def get_policy_proc_token():
    """Get token for policy/procedure sections using fake_users.json login."""
    logger.info("🔐 Authenticating policy/procedure (fake_users.json)...")
    logger.info(f"   Auth URL: {POLICY_AUTH_URL}")
    try:
        # Policy service has its own /auth/login endpoint
        resp = httpx.post(
            POLICY_AUTH_URL,
            json=POLICY_PROC_CREDS,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("access_token") or data.get("token") or data
            if isinstance(token, str):
                logger.info(f"✅ Policy/Procedure token obtained")
                return token
            else:
                logger.error(f"❌ Invalid token format: {data}")
                return None
        else:
            logger.error(f"❌ Auth failed {resp.status_code}: {resp.text}")
            return None
    except httpx.ConnectError as e:
        logger.error(f"❌ Cannot reach {POLICY_AUTH_URL}: {e}")
        logger.error(f"   Make sure policy service is running on Docker network")
        return None
    except Exception as e:
        logger.error(f"❌ Auth error: {e}")
        return None

def query_gateway(token, category, question):
    """Query the gateway with SSE streaming."""
    logger.info(f"\n📨 Query: {category.upper()} — '{question}'")
    logger.info(f"   Token: {token[:20]}...")

    try:
        answer_parts = []
        with httpx.stream(
            "POST",
            f"{GATEWAY_URL}/ai-chatbot/route",
            json={
                "question": question,
                "context": {"category": category}
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        ) as resp:
            if resp.status_code != 200:
                logger.error(f"❌ Gateway error {resp.status_code}: {resp.read().decode(errors='replace')}")
                return False

            buf = ""
            routing_info = None
            token_count = None

            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    line, buf = buf.split("\n\n", 1)
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")

                    if event_type == "meta":
                        routing_info = event.get("routing", {})
                        target = routing_info.get("target_services", [])
                        reason = routing_info.get("routing_reason", "")
                        logger.info(f"   ✓ Routed to: {target} ({reason})")

                    elif event_type == "token":
                        text = event.get("text", "")
                        answer_parts.append(text)
                        logger.info(f"   📝 Answer: {text[:80]}..." if len(text) > 80 else f"   📝 Answer: {text}")

                    elif event_type == "usage":
                        inp = event.get("input_tokens", 0)
                        out = event.get("output_tokens", 0)
                        token_count = (inp, out)
                        logger.info(f"   💰 Tokens: {inp} input, {out} output")

                    elif event_type == "done":
                        logger.info(f"   ✅ Stream complete")

                    elif event_type == "error":
                        logger.error(f"   ❌ Error: {event.get('text', 'unknown')}")
                        return False

                    elif event_type == "blocked":
                        logger.warning(f"   ⚠️  Blocked: {event.get('text', 'unknown')}")

            if not answer_parts:
                logger.error(f"   ❌ No answer received")
                return False

            logger.info(f"   ✅ Test passed")
            return True

    except httpx.ConnectError:
        logger.error(f"❌ Cannot connect to {GATEWAY_URL}")
        return False
    except Exception as e:
        logger.error(f"❌ Error: {type(e).__name__}: {e}")
        return False

def main():
    """Run all tests."""
    logger.info("=" * 80)
    logger.info("SENA AI Chatbot Gateway Test Suite")
    logger.info("=" * 80)
    logger.info(f"🌐 Gateway URL: {GATEWAY_URL}")
    if USE_POLICY_DEV_AUTH:
        logger.info(f"🔑 Policy Auth URL: {POLICY_AUTH_URL}\n")
    else:
        logger.info("🔑 Policy/Procedure auth: ISENA gateway bearer token\n")

    results = {}

    # Test STAFF section (shifts chip)
    logger.info("\n" + "=" * 80)
    logger.info("SECTION 1: STAFF (Shifts Chip)")
    logger.info("=" * 80)
    token = get_staff_client_token()
    if token:
        results["shifts"] = query_gateway(token, "shifts", QUESTIONS["shifts"])
    else:
        results["shifts"] = False

    # Test CLIENT section (client chip)
    logger.info("\n" + "=" * 80)
    logger.info("SECTION 2: CLIENT (Client's Information Chip)")
    logger.info("=" * 80)
    token = get_staff_client_token()
    if token:
        results["client"] = query_gateway(token, "client", QUESTIONS["client"])
    else:
        results["client"] = False

    # Test POLICY section
    logger.info("\n" + "=" * 80)
    logger.info("SECTION 3: POLICY")
    logger.info("=" * 80)
    token = get_policy_proc_token() if USE_POLICY_DEV_AUTH else get_staff_client_token()
    if token:
        results["policy"] = query_gateway(token, "policy", QUESTIONS["policy"])
    else:
        results["policy"] = False

    # Test PROCEDURE section
    logger.info("\n" + "=" * 80)
    logger.info("SECTION 4: PROCEDURE")
    logger.info("=" * 80)
    token = get_policy_proc_token() if USE_POLICY_DEV_AUTH else get_staff_client_token()
    if token:
        results["procedure"] = query_gateway(token, "procedure", QUESTIONS["procedure"])
    else:
        results["procedure"] = False

    # Test CROSS-SECTION BLOCKING (shifts user asks client question)
    logger.info("\n" + "=" * 80)
    logger.info("SECTION 5: CROSS-SECTION BLOCKING (Shifts user → Client question)")
    logger.info("=" * 80)
    logger.info("Expected: System should refuse or redirect to client chip")
    token = get_staff_client_token()
    if token:
        results["cross-section"] = query_gateway(token, "shifts", QUESTIONS["client"])
    else:
        results["cross-section"] = False

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    for section, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{section:20s} {status}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    logger.info("=" * 80)

    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
