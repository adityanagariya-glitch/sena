# pipeline.py
import logging
import uuid
from dotenv import load_dotenv
load_dotenv()

from langfuse import observe, get_client, propagate_attributes

langfuse = get_client()
from rewriter import rewrite_query
from config import MESSAGES
from classifier import classify, should_block
from retriever import retrieve, is_context_empty
from generator import generate_stream
from memory import (
    get_memory_context,
    save_memory,
    create_session,
    get_turns,
)

logger = logging.getLogger(__name__)


@observe(name="rag-pipeline-policy-proc-sync", capture_input=False, capture_output=False)
def run_pipeline(
    question:   str,
    session_id: str  = None,
    user_id:    str  = None,
    org_id:     str  = None,
    role:       str  = None,
    is_new_chat: bool = False,
    doc_type: str = None
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

    with propagate_attributes(user_id=user_id, session_id=session_id):
        # Create new session in DynamoDB if new chat
        if is_new_chat:
            create_session(user_id, session_id, question)

        # Step 1: Read memory context (recent turns + AgentCore)
        try:
            memory_ctx = get_memory_context(user_id, session_id, question)
            recent_turns  = memory_ctx["recent_turns"]
            agentcore_ctx = memory_ctx["agentcore_ctx"]
        except Exception as e:
            logger.error(f"Memory read failed: {e}")
            recent_turns  = ""
            agentcore_ctx = ""

        # Step 2: Classify
        try:
            classification = classify(question, recent_turns=recent_turns)
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            classification = {"label": "NDIS", "confidence": 0.5, "reason": "Classifier error"}

        # Step 3: Block if needed
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

        # Step 3a: Handle greetings — skip retrieval, generate warm response directly
        if classification.get("label") == "GREETING":
            logger.info("Greeting detected — skipping retrieval, generating direct response")
            full_answer = []
            for chunk in generate_stream(
                question=question,
                context="",
                recent_turns=recent_turns,
                agentcore_ctx=agentcore_ctx
            ):
                if chunk.get("type") == "token":
                    full_answer.append(chunk.get("text", ""))
            answer = "".join(full_answer).strip()
            try:
                save_memory(user_id, session_id, question, answer, [])
            except Exception as e:
                logger.error(f"Memory save failed for greeting: {e}")
            return {
                "question":       question,
                "answer":         answer,
                "blocked":        False,
                "block_reason":   None,
                "classification": classification,
                "sources":        [],
                "session_id":     session_id
            }

        # Step 3.5: Rewrite query for better retrieval
        try:
            rewritten_query, _ = rewrite_query(question, recent_turns)
        except Exception as e:
            logger.warning(f"Query rewriting failed: {e} — using original")
            rewritten_query = question

        # Step 4: Retrieve from KB
        try:
            _, context, sources = retrieve(rewritten_query, org_id=org_id, role=role, doc_type=doc_type)
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
            "sources":     clean_sources,
            "session_id":  session_id
        }


@observe(name="rag-pipeline-policy-proc", capture_input=False, capture_output=False)
def run_pipeline_stream(
    question:    str,
    session_id:  str  = None,
    user_id:     str  = None,
    org_id:      str  = None,
    role:        str  = None,
    is_new_chat: bool = False,
    doc_type:    str  = None,
):
    """
    True-streaming version of run_pipeline. Yields SSE-ready event dicts:
        {type: meta,    session_id, label, sources}
        {type: token,   text}
        {type: done,    stop_reason}
        {type: usage,   input_tokens, output_tokens}   ← aggregate across all LLM calls
        {type: blocked, text, label}
        {type: error,   text}

    Tokens are forwarded word-by-word as they arrive from Bedrock.
    Memory is saved after the last event is yielded.
    """
    total_usage = {"input_tokens": 0, "output_tokens": 0}

    def _add(u):
        total_usage["input_tokens"]  += u.get("input_tokens",  0)
        total_usage["output_tokens"] += u.get("output_tokens", 0)

    # ── Validation ──────────────────────────────────────────────────────────────
    if not question or not question.strip():
        yield {"type": "error", "text": "Please enter a valid question."}
        return
    if len(question) > 2000:
        yield {"type": "error", "text": "Your question is too long. Please keep it under 2000 characters."}
        return

    question   = question.strip()
    session_id = session_id or str(uuid.uuid4())
    user_id    = user_id    or "anonymous"

    with propagate_attributes(user_id=user_id, session_id=session_id):
        logger.info(f"Stream pipeline — user: {user_id} | session: {session_id} | q: {question[:80]}")

        if is_new_chat:
            try:
                create_session(user_id, session_id, question)
            except Exception as e:
                logger.error(f"Session create failed: {e}")

        # ── Step 1: Memory ──────────────────────────────────────────────────────────
        try:
            memory_ctx    = get_memory_context(user_id, session_id, question)
            recent_turns  = memory_ctx["recent_turns"]
            agentcore_ctx = memory_ctx["agentcore_ctx"]
        except Exception as e:
            logger.error(f"Memory read failed: {e}")
            recent_turns  = ""
            agentcore_ctx = ""

        # ── Step 2: Classify ────────────────────────────────────────────────────────
        try:
            classification = classify(question, recent_turns=recent_turns)
            _add(classification.get("usage", {}))
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            classification = {"label": "NDIS", "confidence": 0.5, "reason": "Classifier error", "usage": {}}

        label = classification.get("label")

        # Add intent + org to span metadata for filtering in Langfuse UI
        langfuse.update_current_span(metadata={"intent": label, "org_id": org_id, "role": role})

        # ── Step 3: Block ───────────────────────────────────────────────────────────
        blocked, block_message = should_block(classification)
        if blocked:
            logger.info(f"Blocked — {label}")
            yield {"type": "meta",    "session_id": session_id, "label": label, "sources": []}
            yield {"type": "blocked", "text": block_message, "label": label}
            yield {"type": "usage",   "input_tokens": total_usage["input_tokens"], "output_tokens": total_usage["output_tokens"]}
            return

        # ── Step 3a: Greeting ────────────────────────────────────────────────────────
        if label == "GREETING":
            logger.info("Greeting — skipping retrieval, streaming direct response")
            yield {"type": "meta", "session_id": session_id, "label": label, "sources": []}
            full_answer = []
            for chunk in generate_stream(question=question, context="", recent_turns=recent_turns, agentcore_ctx=agentcore_ctx):
                ctype = chunk.get("type")
                if ctype == "token":
                    full_answer.append(chunk.get("text", ""))
                    yield chunk
                elif ctype == "usage":
                    _add(chunk)
                elif ctype in ("done", "blocked", "error"):
                    yield chunk
            yield {"type": "usage", "input_tokens": total_usage["input_tokens"], "output_tokens": total_usage["output_tokens"]}
            try:
                greeting_answer = "".join(full_answer).strip()
                save_memory(user_id, session_id, question, greeting_answer, [])
            except Exception as e:
                logger.error(f"Memory save failed for greeting: {e}")
            return

        # ── Step 3.5: Rewrite ───────────────────────────────────────────────────────
        try:
            rewritten_query, rewriter_usage = rewrite_query(question, recent_turns)
            _add(rewriter_usage)
        except Exception as e:
            logger.warning(f"Query rewriting failed: {e} — using original")
            rewritten_query = question

        # ── Step 4: Retrieve ────────────────────────────────────────────────────────
        try:
            _, context, sources = retrieve(rewritten_query, org_id=org_id, role=role, doc_type=doc_type)
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            yield {"type": "meta",  "session_id": session_id, "label": label, "sources": []}
            yield {"type": "error", "text": MESSAGES["ERROR"]}
            return

        # ── Step 5: Empty context ───────────────────────────────────────────────────
        if is_context_empty(context):
            logger.info("Context empty — returning NOT_IN_KB")
            yield {"type": "meta",  "session_id": session_id, "label": label, "sources": []}
            yield {"type": "token", "text": MESSAGES["NOT_IN_KB"]}
            yield {"type": "done",  "stop_reason": "end_turn"}
            yield {"type": "usage", "input_tokens": total_usage["input_tokens"], "output_tokens": total_usage["output_tokens"]}
            return

        # ── Meta event (sources now known) ──────────────────────────────────────────
        clean_sources = [s.split("/")[-1] for s in sources]
        yield {"type": "meta", "session_id": session_id, "label": label, "sources": clean_sources}

        # ── Step 6: Stream generation ───────────────────────────────────────────────
        full_answer  = []
        is_blocked   = False

        for chunk in generate_stream(
            question      = question,
            context       = context,
            recent_turns  = recent_turns,
            agentcore_ctx = agentcore_ctx,
        ):
            ctype = chunk.get("type")
            if ctype == "token":
                full_answer.append(chunk.get("text", ""))
                yield chunk
            elif ctype == "usage":
                _add(chunk)
            elif ctype == "blocked":
                is_blocked = True
                full_answer.append(chunk.get("text", MESSAGES["BLOCKED"]))
                yield chunk
            elif ctype == "done":
                yield chunk
            elif ctype == "error":
                is_blocked = True
                full_answer.append(chunk.get("text", MESSAGES["ERROR"]))
                yield chunk

        yield {"type": "usage", "input_tokens": total_usage["input_tokens"], "output_tokens": total_usage["output_tokens"]}

        # ── Step 7: Save memory (after all events are yielded) ──────────────────────
        try:
            final_answer = "".join(full_answer).strip()
            if final_answer and not is_blocked:
                save_memory(user_id, session_id, question, final_answer, clean_sources)
        except Exception as e:
            logger.error(f"Memory save failed: {e}")

        logger.info(f"Stream pipeline complete — blocked: {is_blocked}")


if __name__ == "__main__":
    import logging as _logging

    # Buffer log records per turn; flush them after the metadata block so they
    # never interleave with streaming tokens.
    class _TurnBuffer(_logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []
            self.setFormatter(_logging.Formatter("    %(name)s — %(message)s"))
        def emit(self, record):
            self.lines.append(self.format(record))
        def flush_turn(self):
            if self.lines:
                print("  · Log")
                for ln in self.lines:
                    print(ln)
            self.lines.clear()

    _root = _logging.getLogger()
    for _h in _root.handlers[:]:
        _root.removeHandler(_h)
    _buf = _TurnBuffer()
    _root.addHandler(_buf)
    _root.setLevel(_logging.INFO)

    test_user_id    = "test-user"
    test_session_id = str(uuid.uuid4())
    is_new_chat     = True

    SEP = "─" * 60

    print(SEP)
    print(f"  Session : {test_session_id}")
    print(f"  Commands: quit | new | history")
    print(SEP + "\n")

    while True:
        q = input("You: ").strip()
        if not q:
            continue

        if q.lower() == "quit":
            langfuse.flush()
            print("\nGoodbye.\n")
            break

        elif q.lower() == "new":
            test_session_id = str(uuid.uuid4())
            is_new_chat     = True
            print(f"\n  New session: {test_session_id}\n")
            continue

        elif q.lower() == "history":
            turns = get_turns(test_session_id)
            print(f"\n{SEP}")
            print(f"  Chat history ({len(turns)} turns)")
            print(SEP)
            for i, t in enumerate(turns, 1):
                print(f"  [{i}] You : {t['question']}")
                print(f"       Bot : {t['answer'][:120]}{'...' if len(t['answer']) > 120 else ''}")
            print(SEP + "\n")
            continue

        label   = ""
        sources = []
        in_tok  = 0
        out_tok = 0
        _buf.lines.clear()   # discard any stray logs before this turn starts

        print("\nBot: ", end="", flush=True)
        for event in run_pipeline_stream(
            question    = q,
            session_id  = test_session_id,
            user_id     = test_user_id,
            is_new_chat = is_new_chat,
        ):
            etype = event.get("type")
            if etype == "meta":
                label   = event.get("label", "")
                sources = event.get("sources", [])
            elif etype == "token":
                print(event["text"], end="", flush=True)
            elif etype in ("blocked", "error"):
                print(event.get("text", ""), end="", flush=True)
            elif etype == "usage":
                in_tok  = event.get("input_tokens",  0)
                out_tok = event.get("output_tokens", 0)

        is_new_chat = False

        src_str = ", ".join(sources) if sources else "—"
        print(f"\n\n  Label  : {label}")
        print(f"  Sources: {src_str}")
        print(f"  Tokens : {in_tok:,} in  /  {out_tok:,} out")
        _buf.flush_turn()
        print()
