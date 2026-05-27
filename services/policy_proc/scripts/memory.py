# memory.py
import boto3
import logging
from datetime import datetime
from decimal import Decimal

from services.policy_proc.scripts.config import REGION, MEMORY_ID, SESSIONS_TABLE, TURNS_TABLE

logger = logging.getLogger(__name__)

# AgentCore clients
agentcore_control = boto3.client("bedrock-agentcore-control", region_name=REGION)
agentcore_data    = boto3.client("bedrock-agentcore",         region_name=REGION)

# DynamoDB
dynamodb = boto3.resource("dynamodb", region_name=REGION)
sessions_table = dynamodb.Table(SESSIONS_TABLE)
turns_table    = dynamodb.Table(TURNS_TABLE)

TURNS_IN_PROMPT   = 5    # how many past turns to inject into prompt
TURNS_TO_STORE    = 15   # how many turns to keep in DynamoDB per session
TTL_DAYS          = 30   # days before auto-delete
MAX_TURN_ANSWER_LENGTH = 300  # characters per turn to keep in memory


# ── DYNAMODB — SESSION MANAGEMENT ─────────────────────────────────────────────

def create_session(actor_id: str, session_id: str, first_question: str) -> dict:
    """Creates a new chat session in DynamoDB."""
    import time
    now    = datetime.utcnow().isoformat()
    ttl    = int(time.time()) + (TTL_DAYS * 86400)
    title  = first_question[:60] + "..." if len(first_question) > 60 else first_question

    item = {
        "user_id":      actor_id,
        "session_id":   session_id,
        "title":        title,
        "created_at":   now,
        "last_updated": now,
        "ttl":          ttl
    }

    try:
        sessions_table.put_item(Item=item)
        logger.info(f"Session created: {session_id} for user: {actor_id}")
        return item
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        return {}


def get_sessions(actor_id: str) -> list:
    """Returns all chat sessions for a user (sidebar list)."""
    try:
        response = sessions_table.query(
            KeyConditionExpression="user_id = :uid",
            ExpressionAttributeValues={":uid": actor_id},
            ScanIndexForward=False  # most recent first
        )
        return response.get("Items", [])
    except Exception as e:
        logger.error(f"Failed to get sessions: {e}")
        return []


def rename_session(actor_id: str, session_id: str, new_title: str) -> bool:
    """Renames a chat session."""
    try:
        sessions_table.update_item(
            Key={"user_id": actor_id, "session_id": session_id},
            UpdateExpression="SET title = :t, last_updated = :u",
            ExpressionAttributeValues={
                ":t": new_title,
                ":u": datetime.utcnow().isoformat()
            }
        )
        logger.info(f"Session renamed: {session_id} → {new_title}")
        return True
    except Exception as e:
        logger.error(f"Failed to rename session: {e}")
        return False


def update_session_timestamp(actor_id: str, session_id: str):
    """Updates last_updated on a session."""
    try:
        sessions_table.update_item(
            Key={"user_id": actor_id, "session_id": session_id},
            UpdateExpression="SET last_updated = :u",
            ExpressionAttributeValues={":u": datetime.utcnow().isoformat()}
        )
    except Exception as e:
        logger.error(f"Failed to update session timestamp: {e}")


# ── DYNAMODB — TURN MANAGEMENT ────────────────────────────────────────────────

def save_turn(session_id: str, question: str, answer: str, sources: list) -> bool:
    """Saves a conversation turn to DynamoDB."""
    import time
    now    = datetime.utcnow().isoformat()
    ttl    = int(time.time()) + (TTL_DAYS * 86400)
    turn_id = now  # ISO timestamp as sort key keeps chronological order

    try:
        turns_table.put_item(Item={
            "session_id": session_id,
            "turn_id":    turn_id,
            "question":   question,
            "answer":     answer,
            "sources":    sources,
            "timestamp":  now,
            "ttl":        ttl
        })
        logger.info(f"Turn saved: {session_id} at {turn_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save turn: {e}")
        return False


def get_turns(session_id: str, limit: int = TURNS_TO_STORE) -> list:
    """Returns last N turns for a session (for UI display)."""
    try:
        response = turns_table.query(
            KeyConditionExpression="session_id = :sid",
            ExpressionAttributeValues={":sid": session_id},
            ScanIndexForward=False,  # most recent first
            Limit=limit
        )
        turns = response.get("Items", [])
        return list(reversed(turns))  # chronological order for display
    except Exception as e:
        logger.error(f"Failed to get turns: {e}")
        return []


def get_recent_turns_for_prompt(session_id: str) -> str:
    """
    Returns last N turns formatted for injection into the prompt.
    Sliding window — only last TURNS_IN_PROMPT turns injected.
    """
    turns = get_turns(session_id, limit=TURNS_IN_PROMPT)
    if not turns:
        return ""

    formatted = []
    for turn in turns:
        formatted.append(f"User: {turn['question']}")
        answer = turn["answer"]
        if len(answer) > MAX_TURN_ANSWER_LENGTH:
            answer = answer[:MAX_TURN_ANSWER_LENGTH] + "..."
        formatted.append(f"Assistant: {answer}")

    return "\n".join(formatted)


# ── AGENTCORE MEMORY ──────────────────────────────────────────────────────────

def write_to_agentcore(actor_id: str, session_id: str, question: str, answer: str) -> bool:
    """
    Writes a conversation turn to AgentCore Memory.
    AgentCore extracts facts, preferences, and summaries automatically.
    """
    try:
        agentcore_data.create_event(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=datetime.utcnow(),
            payload=[
                {
                    "conversational": {
                        "content": {"text": question},
                        "role":    "USER"
                    }
                },
                {
                    "conversational": {
                        "content": {"text": answer},
                        "role":    "ASSISTANT"
                    }
                }
            ]
        )
        logger.info(f"AgentCore event written — actor: {actor_id} session: {session_id}")
        return True
    except Exception as e:
        logger.error(f"AgentCore write error: {e}")
        return False


def read_from_agentcore(actor_id: str, session_id: str, query: str) -> str:
    try:
        response = agentcore_data.retrieve_memory_records(
            memoryId=MEMORY_ID,
            namespace=f"/facts/{actor_id}",
            searchCriteria={
                "searchQuery": query
            },
            maxResults=5
        )
        records = response.get("memoryRecordSummaries", [])
        if not records:
            return ""
        facts = [r.get("content", {}).get("text", "") for r in records if r.get("content")]
        formatted = "\n".join([f"- {f}" for f in facts if f])
        logger.info(f"AgentCore retrieved {len(records)} records for actor: {actor_id}")
        return formatted
    except Exception as e:
        logger.error(f"AgentCore read error: {e}")
        return ""


# ── COMBINED MEMORY READ ──────────────────────────────────────────────────────

def get_memory_context(actor_id: str, session_id: str, question: str) -> dict:
    """
    Returns all memory context needed before generation:
    - Recent turns from DynamoDB (conversation history)
    - Long-term facts from AgentCore (user preferences, past topics)
    """
    recent_turns  = get_recent_turns_for_prompt(session_id)
    agentcore_ctx = read_from_agentcore(actor_id, session_id, question)

    return {
        "recent_turns":  recent_turns,
        "agentcore_ctx": agentcore_ctx
    }


def save_memory(actor_id: str, session_id: str, question: str, answer: str, sources: list):
    """
    Saves memory safely:
    - DynamoDB save should NEVER fail because of AgentCore
    """
    try:
        save_turn(session_id, question, answer, sources)
    except Exception as e:
        logger.error(f"DynamoDB turn save failed: {e}")
    try:
        update_session_timestamp(actor_id, session_id)
    except Exception as e:
        logger.error(f"Session timestamp update failed: {e}")
    try:
        write_to_agentcore(actor_id, session_id, question, answer)
    except Exception as e:
        logger.error(f"AgentCore write failed (non-blocking): {e}")


if __name__ == "__main__":
    import uuid

    # Test with a dummy user and session
    test_user_id    = "test-user-001"
    test_session_id = str(uuid.uuid4())

    print("Testing session creation...")
    create_session(test_user_id, test_session_id, "What is the safeguarding policy?")

    print("Testing turn save...")
    save_turn(test_session_id, "What is the safeguarding policy?",
              "The safeguarding policy protects participants from harm.", ["Participant Safeguarding Policy.pdf"])

    print("Testing turn retrieval...")
    turns = get_turns(test_session_id)
    print(f"Turns: {len(turns)}")

    print("Testing prompt context...")
    ctx = get_recent_turns_for_prompt(test_session_id)
    print(f"Context:\n{ctx}")

    print("Testing AgentCore write...")
    write_to_agentcore(test_user_id, test_session_id,
                       "What is the safeguarding policy?",
                       "The safeguarding policy protects participants from harm.")

    print("Testing session list...")
    sessions = get_sessions(test_user_id)
    print(f"Sessions: {len(sessions)}")

    print("\n memory.py tests complete")