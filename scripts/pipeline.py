# pipeline.py
import logging
import uuid
from rewriter import rewrite_query
from config import MESSAGES
from classifier import classify, should_block
from retriever import retrieve, is_context_empty
from generator import generate_stream
from memory import (
    get_memory_context,
    save_memory,
    create_session,
    get_sessions,
    get_turns
)

logger = logging.getLogger(__name__)


def run_pipeline(
    question:   str,
    session_id: str  = None,
    user_id:    str  = None,
    org_id:     str  = None,
    role:       str  = None,
    is_new_chat: bool = False
) -> dict:
    """
    Full RAG pipeline with memory:
    1. Validate input
    2. Classify intent
    3. Block if off-topic/harmful/sensitive
    4. Read memory context (DynamoDB + AgentCore)
    5. Retrieve from KB
    6. Generate answer with memory injected
    7. Save turn to DynamoDB + AgentCore
    """

    # Input validation
    if not question or not question.strip():
        logger.warning("Empty question received")
        return {
            "question":    question,
            "answer":      "Please enter a valid question.",
            "blocked":     True,
            "block_reason":"EMPTY_INPUT",
            "classification": {},
            "sources":     [],
            "session_id":  session_id
        }

    if len(question) > 2000:
        logger.warning(f"Question too long: {len(question)} chars")
        return {
            "question":    question,
            "answer":      "Your question is too long. Please keep it under 2000 characters.",
            "blocked":     True,
            "block_reason":"INPUT_TOO_LONG",
            "classification": {},
            "sources":     [],
            "session_id":  session_id
        }

    question   = question.strip()
    session_id = session_id or str(uuid.uuid4())
    user_id    = user_id    or "anonymous"

    logger.info(f"Pipeline started — user: {user_id} | session: {session_id} | q: {question[:80]}")

    # Create new session in DynamoDB if new chat
    if is_new_chat:
        create_session(user_id, session_id, question)

    # Step 1: Classify
    try:
        classification = classify(question)
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        classification = {"label": "NDIS", "confidence": 0.5, "reason": "Classifier error"}

    # Step 2: Block if needed
    blocked, block_message = should_block(classification)
    if blocked:
        logger.info(f"Blocked — {classification['label']}")
        return {
            "question":    question,
            "answer":      block_message,
            "blocked":     True,
            "block_reason":classification["label"],
            "classification": classification,
            "sources":     [],
            "session_id":  session_id
        }

    # Step 3: Read memory context
    try:
        memory_ctx = get_memory_context(user_id, session_id, question)
        recent_turns  = memory_ctx["recent_turns"]
        agentcore_ctx = memory_ctx["agentcore_ctx"]
    except Exception as e:
        logger.error(f"Memory read failed: {e}")
        recent_turns  = ""
        agentcore_ctx = ""
    
    # Step 3.5: Rewrite query for better retrieval
    try:
        rewritten_query = rewrite_query(question, recent_turns)
    except Exception as e:
        logger.warning(f"Query rewriting failed: {e} — using original")
        rewritten_query = question

    # Step 4: Retrieve from KB
    try:
        chunks, context, sources = retrieve(rewritten_query, org_id=org_id, role=role)
    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        return {
            "question":    question,
            "answer":      MESSAGES["ERROR"],
            "blocked":     False,
            "block_reason":"RETRIEVAL_ERROR",
            "classification": classification,
            "sources":     [],
            "session_id":  session_id
        }

    # Step 5: Check empty context
    if is_context_empty(context):
        logger.info("Context empty — returning NOT_IN_KB")
        return {
            "question":    question,
            "answer":      MESSAGES["NOT_IN_KB"],
            "blocked":     False,
            "block_reason":"NOT_IN_KB",
            "classification": classification,
            "sources":     [],
            "session_id":  session_id
        }   
    
    # Step 6: Generate with memory injected
    full_answer  = []
    blocked      = False
    block_reason = None

    for chunk in generate_stream(
        question=question,
        context=context,
        recent_turns=recent_turns,
        agentcore_ctx=agentcore_ctx
    ):
        ctype = chunk.get("type")
        if ctype == "token":
            full_answer.append(chunk.get("text", ""))
        elif ctype == "blocked":
            blocked      = True
            block_reason = "GUARDRAIL_BLOCKED"
            full_answer.append(chunk.get("text", MESSAGES["BLOCKED"]))
        elif ctype == "error":
            blocked      = True
            block_reason = "GENERATION_ERROR"
            full_answer.append(chunk.get("text", MESSAGES["ERROR"]))
        elif ctype == "done":
            pass

    final_answer = "".join(full_answer).strip()
    result = {
        "answer":  final_answer,
        "blocked": blocked,
}

    # Step 7: Save memory
    try:
        clean_sources = [s.split("/")[-1] for s in sources]
        if result["answer"]:
            save_memory(
                user_id,
                session_id,
                question,
                result["answer"],
                clean_sources
            )
    except Exception as e:
        logger.error(f"Memory save failed: {e}")

    logger.info(f"Pipeline complete — blocked: {result['blocked']}")

    return {
        "question":    question,
        "answer":      result["answer"],
        "blocked":     result["blocked"],
        "block_reason":block_reason,
        "classification": classification,
        "sources":     [s.split("/")[-1] for s in sources],
        "session_id":  session_id
    }


if __name__ == "__main__":
    # # Test org isolation
    # print("\n=== ORG_SUNRISE QUERY ===")
    # result = run_pipeline("what is the dignity of risk policy?", user_id="test-user", session_id=str(uuid.uuid4()), org_id="org_sunrise", is_new_chat=True)
    # print(f"Answer: {result['answer'][:200]}")
    # print(f"Sources: {result['sources']}")

    # print("\n=== ORG_HORIZONS QUERY ===")
    # result = run_pipeline("what is the leave policy?", user_id="test-user", session_id=str(uuid.uuid4()), org_id="org_horizons", is_new_chat=True)
    # print(f"Answer: {result['answer'][:200]}")
    # print(f"Sources: {result['sources']}")

    # print("\n=== NDIS ONLY QUERY ===")
    # result = run_pipeline("what is the safeguarding policy?", user_id="test-user", session_id=str(uuid.uuid4()), org_id="org_sunrise", is_new_chat=True)
    # print(f"Answer: {result['answer'][:200]}")
    # print(f"Sources: {result['sources']}")

    # print("\n=== CROSS ORG TEST (org_sunrise asking org_horizons question) ===")
    # result = run_pipeline("what is the allowances policy?", user_id="test-user", session_id=str(uuid.uuid4()), org_id="org_sunrise", is_new_chat=True)
    # print(f"Answer: {result['answer'][:200]}")
    # print(f"Sources: {result['sources']}")


    test_user_id    = "test-user"
    test_session_id = str(uuid.uuid4())
    is_new_chat     = True

    print(f"Session ID: {test_session_id}")
    print("Type 'quit' to exit, 'new' to start new chat, 'history' to see turns\n")

    while True:
        q = input("You: ").strip()

        if q.lower() == "quit":
            break

        elif q.lower() == "new":
            test_session_id = str(uuid.uuid4())
            is_new_chat     = True
            print(f"New session: {test_session_id}\n")
            continue

        elif q.lower() == "history":
            turns = get_turns(test_session_id)
            print(f"\n--- Chat History ({len(turns)} turns) ---")
            for t in turns:
                print(f"Q: {t['question']}")
                print(f"A: {t['answer'][:150]}...")
                print()
            continue

        result = run_pipeline(
            question    = q,
            session_id  = test_session_id,
            user_id     = test_user_id,
            is_new_chat = is_new_chat
        )

        is_new_chat = False  # only True on first question

        print(f"\nBot: {result['answer']}")
        print(f"[{result['classification'].get('label')} | Sources: {result['sources']}]\n")