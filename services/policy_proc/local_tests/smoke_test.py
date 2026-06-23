# local_tests/smoke_tests.py
# Smoke tests for SENA RAG API.
# Requires FastAPI running on port 8000.
#
# Run:
#     python local_tests/smoke_tests.py

import requests
import json
import uuid
import sys

API_BASE = "http://localhost:8000"

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

# ── Results tracker ───────────────────────────────────────────────────────────
results = {"passed": 0, "failed": 0, "errors": []}


def passed(name: str):
    results["passed"] += 1
    print(f"  {GREEN}✓{RESET} {name}")


def failed(name: str, reason: str):
    results["failed"] += 1
    results["errors"].append(f"{name}: {reason}")
    print(f"  {RED}✗{RESET} {name}")
    print(f"    {RED}→ {reason}{RESET}")


def section(title: str):
    print(f"\n{BOLD}{title}{RESET}")
    print("─" * 50)


# ── Helpers ───────────────────────────────────────────────────────────────────

def login(login_id: str, password: str) -> tuple[int, dict]:
    """Returns (status_code, response_body)."""
    r = requests.post(
        f"{API_BASE}/auth/login",
        json={"login_id": login_id, "password": password},
        timeout=10
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def stream_query(token: str, question: str, org_id: str = None) -> dict:
    """
    Sends a streaming query and collects all SSE events.
    Returns dict with keys: meta, tokens, done, blocked, error
    """
    session_id = str(uuid.uuid4())
    payload = {
        "question":    question,
        "session_id":  session_id,
        "is_new_chat": True
    }

    collected = {
        "meta":       None,
        "tokens":     [],
        "done":       None,
        "blocked":    None,
        "error":      None,
        "session_id": session_id,
        "full_answer": ""
    }

    try:
        with requests.post(
            f"{API_BASE}/query/stream",
            json=payload,
            headers=auth_headers(token),
            stream=True,
            timeout=120
        ) as resp:
            if resp.status_code != 200:
                collected["error"] = f"HTTP {resp.status_code}"
                return collected

            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                etype = event.get("type")

                if etype == "meta":
                    collected["meta"] = event
                elif etype == "token":
                    collected["tokens"].append(event.get("text", ""))
                elif etype == "done":
                    collected["done"] = event
                elif etype == "blocked":
                    collected["blocked"] = event
                elif etype == "error":
                    collected["error"] = event

    except requests.exceptions.ConnectionError:
        collected["error"] = "Cannot reach server — is FastAPI running on port 8000?"
    except Exception as exc:
        collected["error"] = str(exc)

    collected["full_answer"] = "".join(collected["tokens"])
    return collected


def get_turns(token: str, session_id: str) -> list:
    r = requests.post(
        f"{API_BASE}/get_turns",
        json={"session_id": session_id},
        headers=auth_headers(token),
        timeout=10
    )
    if r.status_code == 200:
        return r.json().get("turns", [])
    return []


# ══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 1 — Authentication
# ══════════════════════════════════════════════════════════════════════════════

def test_auth():
    section("1. Authentication")

    # ── 1.1 Valid login — Sunrise user
    try:
        status, data = login("sunrise\\alice.walker", "Test@1234")
        if status == 200 and data.get("token"):
            passed("Valid login returns 200 + token (sunrise\\alice.walker)")
        else:
            failed("Valid login returns 200 + token", f"Got status {status}")
    except Exception as e:
        failed("Valid login returns 200 + token", str(e))

    # ── 1.2 Valid login — Horizons user
    try:
        status, data = login("horizons\\priya.mehta", "Test@5678")
        if status == 200 and data.get("token"):
            passed("Valid login returns 200 + token (horizons\\priya.mehta)")
        else:
            failed("Valid login returns 200 + token (horizons)", f"Got status {status}")
    except Exception as e:
        failed("Valid login returns 200 + token (horizons)", str(e))

    # ── 1.3 Valid login — Superadmin
    try:
        status, data = login("ndis\\admin.super", "Admin@9999")
        if status == 200 and data.get("token"):
            passed("Valid login returns 200 + token (ndis\\admin.super)")
        else:
            failed("Valid login returns 200 + token (superadmin)", f"Got status {status}")
    except Exception as e:
        failed("Valid login returns 200 + token (superadmin)", str(e))

    # ── 1.4 Wrong password
    try:
        status, data = login("sunrise\\alice.walker", "WrongPassword")
        if status == 401:
            passed("Wrong password returns 401")
        else:
            failed("Wrong password returns 401", f"Got status {status}")
    except Exception as e:
        failed("Wrong password returns 401", str(e))

    # ── 1.5 Non-existent user
    try:
        status, data = login("sunrise\\ghost.user", "Test@1234")
        if status == 401:
            passed("Non-existent user returns 401")
        else:
            failed("Non-existent user returns 401", f"Got status {status}")
    except Exception as e:
        failed("Non-existent user returns 401", str(e))

    # ── 1.6 Inactive user
    try:
        status, data = login("sunrise\\inactive.user", "Test@0000")
        if status == 403:
            passed("Inactive user returns 403")
        else:
            failed("Inactive user returns 403", f"Got status {status}")
    except Exception as e:
        failed("Inactive user returns 403", str(e))

    # ── 1.7 Token contains correct claims
    try:
        status, data = login("sunrise\\ben.carter", "Test@1234")
        if status == 200:
            if (data.get("org_id") == "org_sunrise" and
                data.get("role") == "coordinator" and
                data.get("user_id") == "u-sunrise-co-01"):
                passed("Token claims contain correct org_id, role, user_id")
            else:
                failed("Token claims correct", f"Got: {data}")
        else:
            failed("Token claims correct", f"Login failed with {status}")
    except Exception as e:
        failed("Token claims correct", str(e))

    # ── 1.8 No token — protected endpoint returns 401
    try:
        r = requests.post(f"{API_BASE}/list_sessions", json={}, timeout=10)
        if r.status_code == 401:
            passed("No token on protected endpoint returns 401")
        else:
            failed("No token returns 401", f"Got status {r.status_code}")
    except Exception as e:
        failed("No token returns 401", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 2 — Streaming Query
# ══════════════════════════════════════════════════════════════════════════════

def test_streaming():
    section("2. Streaming Query")

    # Login first
    _, data = login("sunrise\\alice.walker", "Test@1234")
    token = data.get("token")
    if not token:
        failed("Streaming setup", "Could not get token — skipping streaming tests")
        return

    # ── 2.1 Valid NDIS question returns stream
    try:
        result = stream_query(token, "What is the safeguarding policy?")
        if result["error"] and "Cannot reach" in str(result["error"]):
            failed("Valid NDIS question streams correctly", result["error"])
        elif result["meta"] is not None:
            passed("Valid NDIS question returns meta event")
        else:
            failed("Valid NDIS question returns meta event", "No meta event received")
    except Exception as e:
        failed("Valid NDIS question streams correctly", str(e))

    # ── 2.2 Stream contains tokens
    try:
        result = stream_query(token, "What is the safeguarding policy?")
        if result["tokens"]:
            passed(f"Stream contains tokens ({len(result['tokens'])} received)")
        else:
            failed("Stream contains tokens", "No tokens received")
    except Exception as e:
        failed("Stream contains tokens", str(e))

    # ── 2.3 Stream ends with done event
    try:
        result = stream_query(token, "What is the safeguarding policy?")
        if result["done"] is not None:
            passed("Stream ends with done event")
        else:
            failed("Stream ends with done event", "No done event received")
    except Exception as e:
        failed("Stream ends with done event", str(e))

    # ── 2.4 Off-topic question returns blocked event
    try:
        result = stream_query(token, "What is the capital of France?")
        if result["blocked"] is not None:
            passed("Off-topic question returns blocked event")
        else:
            failed("Off-topic question returns blocked event",
                   f"Got tokens instead: {result['full_answer'][:100]}")
    except Exception as e:
        failed("Off-topic question returns blocked event", str(e))

    # ── 2.5 Harmful question returns blocked event
    try:
        result = stream_query(token, "How do I hurt someone?")
        if result["blocked"] is not None:
            passed("Harmful question returns blocked event")
        else:
            failed("Harmful question returns blocked event",
                   f"Got: {result['full_answer'][:100]}")
    except Exception as e:
        failed("Harmful question returns blocked event", str(e))

    # ── 2.6 Sensitive question returns blocked event
    try:
        result = stream_query(token, "My participant John Smith at 42 Main St needs help")
        if result["blocked"] is not None:
            passed("Sensitive question returns blocked event")
        else:
            failed("Sensitive question returns blocked event",
                   f"Got: {result['full_answer'][:100]}")
    except Exception as e:
        failed("Sensitive question returns blocked event", str(e))

    # ── 2.7 Empty question returns 400
    try:
        r = requests.post(
            f"{API_BASE}/query/stream",
            json={"question": "", "session_id": str(uuid.uuid4())},
            headers=auth_headers(token),
            timeout=10
        )
        if r.status_code == 400:
            passed("Empty question returns 400")
        else:
            failed("Empty question returns 400", f"Got status {r.status_code}")
    except Exception as e:
        failed("Empty question returns 400", str(e))

    # ── 2.8 Meta event contains session_id and sources
    try:
        result = stream_query(token, "How do I report an incident?")
        meta = result["meta"]
        if meta and meta.get("session_id") and "sources" in meta:
            passed("Meta event contains session_id and sources")
        else:
            failed("Meta event contains session_id and sources",
                   f"Meta: {meta}")
    except Exception as e:
        failed("Meta event contains session_id and sources", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 3 — Memory Save
# ══════════════════════════════════════════════════════════════════════════════

def test_memory():
    section("3. Memory Save")

    _, data = login("sunrise\\ben.carter", "Test@1234")
    token = data.get("token")
    if not token:
        failed("Memory setup", "Could not get token — skipping memory tests")
        return

    session_id = str(uuid.uuid4())
    question   = "What is the safeguarding policy?"

    # ── 3.1 Send a query and check turn is saved
    try:
        payload = {
            "question":    question,
            "session_id":  session_id,
            "is_new_chat": True
        }
        with requests.post(
            f"{API_BASE}/query/stream",
            json=payload,
            headers=auth_headers(token),
            stream=True,
            timeout=120
        ) as resp:
            # Drain the stream fully
            for _ in resp.iter_lines():
                pass

        # Now check turns
        import time
        time.sleep(2)   # small wait for DynamoDB write to settle

        turns = get_turns(token, session_id)
        if turns:
            passed(f"Turn saved to DynamoDB after query ({len(turns)} turn(s))")
        else:
            failed("Turn saved to DynamoDB", "No turns found after query")
    except Exception as e:
        failed("Turn saved to DynamoDB", str(e))

    # ── 3.2 Turn contains correct question
    try:
        turns = get_turns(token, session_id)
        if turns and turns[0].get("question") == question:
            passed("Saved turn contains correct question")
        else:
            failed("Saved turn contains correct question",
                   f"Got: {turns[0].get('question') if turns else 'no turns'}")
    except Exception as e:
        failed("Saved turn contains correct question", str(e))

    # ── 3.3 Turn contains non-empty answer
    try:
        turns = get_turns(token, session_id)
        if turns and turns[0].get("answer"):
            passed("Saved turn contains non-empty answer")
        else:
            failed("Saved turn contains non-empty answer",
                   "Answer is empty or missing")
    except Exception as e:
        failed("Saved turn contains non-empty answer", str(e))

    # ── 3.4 Another user cannot access this session
    try:
        _, other_data = login("horizons\\priya.mehta", "Test@5678")
        other_token = other_data.get("token")
        if other_token:
            r = requests.post(
                f"{API_BASE}/get_turns",
                json={"session_id": session_id},
                headers=auth_headers(other_token),
                timeout=10
            )
            if r.status_code == 403:
                passed("Another user cannot access session turns (403)")
            else:
                failed("Another user cannot access session turns",
                       f"Got status {r.status_code} — expected 403")
    except Exception as e:
        failed("Another user cannot access session turns", str(e))

    # ── 3.5 Multi-turn — second question in same session saves correctly
    try:
        second_question = "How do I report an incident?"
        payload = {
            "question":    second_question,
            "session_id":  session_id,
            "is_new_chat": False
        }
        with requests.post(
            f"{API_BASE}/query/stream",
            json=payload,
            headers=auth_headers(token),
            stream=True,
            timeout=120
        ) as resp:
            for _ in resp.iter_lines():
                pass

        import time
        time.sleep(2)

        turns = get_turns(token, session_id)
        if len(turns) >= 2:
            passed(f"Multi-turn saves correctly ({len(turns)} turns in session)")
        else:
            failed("Multi-turn saves correctly",
                   f"Expected ≥2 turns, got {len(turns)}")
    except Exception as e:
        failed("Multi-turn saves correctly", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# TEST SUITE 4 — Org Isolation
# ══════════════════════════════════════════════════════════════════════════════

def test_org_isolation():
    section("4. Org Isolation")

    # Login both users
    _, sunrise_data  = login("sunrise\\alice.walker",  "Test@1234")
    _, horizons_data = login("horizons\\priya.mehta",  "Test@5678")
    _, admin_data    = login("ndis\\admin.super",       "Admin@9999")

    sunrise_token  = sunrise_data.get("token")
    horizons_token = horizons_data.get("token")
    admin_token    = admin_data.get("token")

    if not all([sunrise_token, horizons_token, admin_token]):
        failed("Org isolation setup", "Could not get tokens — skipping isolation tests")
        return

    # Use a generic NDIS question both orgs should answer
    ndis_question = "What is the safeguarding policy?"

    # ── 4.1 Sunrise user gets answer from NDIS or Sunrise docs only
    try:
        result = stream_query(sunrise_token, ndis_question)
        sources = result.get("meta", {}).get("sources", []) if result.get("meta") else []
        horizons_sources = [s for s in sources if "horizons" in s.lower()]
        if not horizons_sources:
            passed("Sunrise user gets no org_horizons sources")
        else:
            failed("Sunrise user gets no org_horizons sources",
                   f"Got horizons sources: {horizons_sources}")
    except Exception as e:
        failed("Sunrise user gets no org_horizons sources", str(e))

    # ── 4.2 Horizons user gets answer from NDIS or Horizons docs only
    try:
        result = stream_query(horizons_token, ndis_question)
        sources = result.get("meta", {}).get("sources", []) if result.get("meta") else []
        sunrise_sources = [s for s in sources if "sunrise" in s.lower()]
        if not sunrise_sources:
            passed("Horizons user gets no org_sunrise sources")
        else:
            failed("Horizons user gets no org_sunrise sources",
                   f"Got sunrise sources: {sunrise_sources}")
    except Exception as e:
        failed("Horizons user gets no org_sunrise sources", str(e))

    # ── 4.3 Sunrise user asking Horizons-specific question gets NOT_IN_KB
    try:
        # Use a question that would only exist in horizons docs
        result = stream_query(sunrise_token, "What is the horizons allowances policy?")
        answer = result["full_answer"].lower()
        blocked = result["blocked"]
        not_in_kb = (
            blocked is not None or
            "don't have the authority" in answer or
            "not covered" in answer or
            "check with your supervisor" in answer
        )
        if not_in_kb:
            passed("Sunrise user cannot access Horizons-specific content")
        else:
            failed("Sunrise user cannot access Horizons-specific content",
                   f"Got answer: {result['full_answer'][:150]}")
    except Exception as e:
        failed("Sunrise user cannot access Horizons-specific content", str(e))

    # ── 4.4 Horizons user asking Sunrise-specific question gets NOT_IN_KB
    try:
        result = stream_query(horizons_token, "What is the sunrise safeguarding policy?")
        answer = result["full_answer"].lower()
        blocked = result["blocked"]
        not_in_kb = (
            blocked is not None or
            "don't have the authority" in answer or
            "not covered" in answer or
            "check with your supervisor" in answer
        )
        if not_in_kb:
            passed("Horizons user cannot access Sunrise-specific content")
        else:
            failed("Horizons user cannot access Sunrise-specific content",
                   f"Got answer: {result['full_answer'][:150]}")
    except Exception as e:
        failed("Horizons user cannot access Sunrise-specific content", str(e))

    # ── 4.5 Superadmin gets answer (no org filter applied)
    try:
        result = stream_query(admin_token, ndis_question)
        if result["full_answer"] or result["blocked"]:
            passed("Superadmin receives a response (no filter blocking)")
        else:
            failed("Superadmin receives a response",
                   "No answer and no blocked event")
    except Exception as e:
        failed("Superadmin receives a response", str(e))

    # ── 4.6 Both users can access NDIS docs (shared)
    try:
        sunrise_result  = stream_query(sunrise_token,  "How do I report an incident?")
        horizons_result = stream_query(horizons_token, "How do I report an incident?")

        sunrise_answered  = bool(sunrise_result["full_answer"])
        horizons_answered = bool(horizons_result["full_answer"])

        if sunrise_answered and horizons_answered:
            passed("Both orgs can access shared NDIS docs")
        else:
            failed("Both orgs can access shared NDIS docs",
                   f"Sunrise answered: {sunrise_answered} | Horizons answered: {horizons_answered}")
    except Exception as e:
        failed("Both orgs can access shared NDIS docs", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}SENA RAG — Smoke Tests{RESET}")
    print(f"API: {API_BASE}")
    print("=" * 50)

    # Check server is reachable first
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        if r.status_code == 200:
            print(f"{GREEN}✓ Server reachable{RESET}")
        else:
            print(f"{RED}✗ Server returned {r.status_code} on /health{RESET}")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"{RED}✗ Cannot reach server at {API_BASE}{RESET}")
        print(f"{YELLOW}  Make sure FastAPI is running: uvicorn app.main:app --reload --port 8000{RESET}")
        sys.exit(1)

    # Run all suites
    test_auth()
    test_streaming()
    test_memory()
    test_org_isolation()

    # Summary
    total = results["passed"] + results["failed"]
    print(f"\n{'=' * 50}")
    print(f"{BOLD}Results: {results['passed']}/{total} passed{RESET}")

    if results["failed"]:
        print(f"\n{RED}Failed tests:{RESET}")
        for err in results["errors"]:
            print(f"  {RED}✗ {err}{RESET}")
        sys.exit(1)
    else:
        print(f"{GREEN}All tests passed ✓{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()