# lambda_function.py
# Main query handler Lambda.
# Receives requests from API Gateway, routes to correct action.
#
# Actions:
#   query          → run full RAG pipeline
#   new_session    → create new chat session
#   list_sessions  → get session list for sidebar
#   get_turns      → get turn history for a session
#   rename_session → rename a chat session

import json
import logging
import uuid

<<<<<<< HEAD:services/policy_proc/scripts/lambda_function.py
from services.policy_proc.scripts.pipeline import run_pipeline
from services.policy_proc.scripts.memory   import create_session, get_sessions, get_turns, rename_session
=======
from pipeline import run_pipeline
from memory   import create_session, get_sessions, get_turns, rename_session
>>>>>>> 0632581 (changes in policy-proc):scripts/lambda_function.py

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    try:
        # Parse body
        body   = json.loads(event.get("body", "{}"))
        action = body.get("action", "query")

        # Extract user identity from Cognito JWT claims (via API Gateway authorizer)
        # Falls back to body values for local/QA testing without Cognito
        request_context = event.get("requestContext", {})
        authorizer      = request_context.get("authorizer", {})
        claims          = authorizer.get("claims", {})

        user_id = claims.get("sub",              body.get("user_id", "anonymous"))
        org_id  = claims.get("custom:org_id",    body.get("org_id",  None))
        role    = claims.get("custom:role",      body.get("role",    None))

        logger.info(f"Action: {action} | User: {user_id} | Org: {org_id} | Role: {role}")

        # ── QUERY ─────────────────────────────────────────────────────────────
        if action == "query":
            question   = body.get("question", "").strip()
            session_id = body.get("session_id") or str(uuid.uuid4())
            is_new     = body.get("is_new_chat", False)

            if not question:
                return response(400, {"error": "question is required"})

            result = run_pipeline(
                question   = question,
                session_id = session_id,
                user_id    = user_id,
                org_id     = org_id,
                role       = role,
                is_new_chat= is_new
            )

            return response(200, {
                "answer":       result["answer"],
                "sources":      result["sources"],
                "blocked":      result["blocked"],
                "block_reason": result["block_reason"],
                "session_id":   result["session_id"],
                "label":        result["classification"].get("label")
            })

        # ── NEW SESSION ───────────────────────────────────────────────────────
        elif action == "new_session":
            session_id = str(uuid.uuid4())
            return response(200, {"session_id": session_id})

        # ── LIST SESSIONS ─────────────────────────────────────────────────────
        elif action == "list_sessions":
            sessions = get_sessions(user_id)
            return response(200, {"sessions": sessions})

        # ── GET TURNS ─────────────────────────────────────────────────────────
        elif action == "get_turns":
            session_id = body.get("session_id")
            if not session_id:
                return response(400, {"error": "session_id is required"})
            turns = get_turns(session_id)
            return response(200, {"turns": turns})

        # ── RENAME SESSION ────────────────────────────────────────────────────
        elif action == "rename_session":
            session_id = body.get("session_id")
            new_title  = body.get("title")
            if not session_id or not new_title:
                return response(400, {"error": "session_id and title are required"})
            rename_session(user_id, session_id, new_title)
            return response(200, {"success": True})

        else:
            return response(400, {"error": f"Unknown action: {action}"})

    except Exception as e:
        logger.error(f"Lambda error: {e}", exc_info=True)
        return response(500, {"error": "Internal server error"})


def response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type":                 "application/json",
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS"
        },
        "body": json.dumps(body, default=str)
    }