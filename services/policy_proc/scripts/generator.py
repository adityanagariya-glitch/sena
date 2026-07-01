# generator.py
import boto3
import logging
from datetime import datetime, timezone
from langfuse import observe, get_client

langfuse = get_client()

from config import REGION, GENERATION_MODEL, MESSAGES
from prompt import SYSTEM_PROMPTS, ACTIVE_PROMPT_VERSION

logger = logging.getLogger(__name__)

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)


@observe(as_type="generation", name="generate", capture_input=False, capture_output=False)
def generate_stream(
    question: str,
    context: str,
    recent_turns: str = "",
    agentcore_ctx: str = ""
):
    """
    Streams response token-by-token from Bedrock Claude.
    Returns generator events:
        {type: token, text: "..."}
        {type: done, stop_reason: "..."}
        {type: blocked, text: "..."}
        {type: error, text: "..."}
    """
    # Build memory section
    memory_section = ""
    if agentcore_ctx:
        memory_section += (
            f"\n## What I know about you\n"
            f"{agentcore_ctx}\n"
        )
    if recent_turns:
        memory_section += (
            f"\n## Recent conversation\n"
            f"{recent_turns}\n"
        )
    # Prompt
    user_message = f"""
You must ONLY use the information explicitly provided in the policy context below to answer the question.

STRICT RULES:
- If the answer is clearly in the context → answer from it
- If the answer is partially in the context → answer only what is covered, say the rest isn't available
- If the answer is NOT in the context at all → respond exactly with: "{MESSAGES['NOT_IN_KB']}"
- NEVER use your own knowledge, training data, or general understanding to answer
- NEVER make assumptions or inferences beyond what is explicitly stated
- NEVER generate salary figures, timeframes, or policy details that aren't in the context

Source rules:
- Answer ONLY from the policy context provided below
- Do not mention NDIS guidelines vs organisation policy distinction
- Do not suggest the user check other sources unless the answer is genuinely incomplete
- The context you receive is already scoped to the correct source for this user and question, so always answer from it without caveats. 

{memory_section}

## Policy context
{context}

## Current question
{question}

## Special instruction
If the question is a greeting or conversational message (hi, hello, good morning, thanks, etc.)
with no policy context available — respond warmly in 1 sentence and invite a policy question.
Do not use the NOT_IN_KB message for greetings.
"""
    langfuse.update_current_generation(model=GENERATION_MODEL, input=question)
    _answer_parts = []
    _first_token = True

    # Streaming generation
    try:
        response = bedrock_runtime.converse_stream(
            modelId=GENERATION_MODEL,
            system=[
                {"text": SYSTEM_PROMPTS[ACTIVE_PROMPT_VERSION]},
                {"cachePoint": {"type": "default"}},
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": user_message
                        }
                    ]
                }
            ],
            inferenceConfig={
                "temperature": 0.3,
                "maxTokens": 1024
            }
        )
        stream = response.get("stream")
        if not stream:
            yield {
                "type": "error",
                "text": "No stream returned from model."
            }
            return
        for event in stream:
            # Token delta
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    if _first_token:
                        langfuse.update_current_generation(
                            completion_start_time=datetime.now(timezone.utc)
                        )
                        _first_token = False
                    _answer_parts.append(delta["text"])
                    yield {
                        "type": "token",
                        "text": delta["text"]
                    }
            # Stream finished
            elif "messageStop" in event:
                stop_reason = event["messageStop"].get(
                    "stopReason",
                    "end_turn"
                )
                # Guardrail interruption
                if stop_reason == "guardrail_intervened":
                    yield {
                        "type": "blocked",
                        "text": MESSAGES["BLOCKED"]
                    }
                else:
                    yield {
                        "type": "done",
                        "stop_reason": stop_reason
                    }
            # Token usage — emitted by Bedrock after messageStop
            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                in_tok  = usage.get("inputTokens",  0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0)
                out_tok = usage.get("outputTokens", 0)
                langfuse.update_current_generation(
                    output="".join(_answer_parts),
                    usage_details={"input": in_tok, "output": out_tok, "total": in_tok + out_tok},
                    metadata={"service": "policy_proc_generator"},
                )
                yield {
                    "type": "usage",
                    "input_tokens":  in_tok,
                    "output_tokens": out_tok,
                    "total_tokens":  in_tok + out_tok,
                }
    # Error handling
    except Exception as e:
        logger.error(f"Streaming generator error: {e}")
        yield {
            "type": "error",
            "text": MESSAGES["ERROR"]
        }

# Local test
if __name__ == "__main__":

    test_context = """
The Participant Safeguarding Policy ensures all participants are protected
from abuse, neglect, and exploitation.
All staff must report any safeguarding concerns immediately to their supervisor.
"""
    while True:
        q = input("\nEnter question (or 'quit'): ").strip()
        if q.lower() == "quit":
            break
        print("\nAssistant: ", end="", flush=True)
        for chunk in generate_stream(q, test_context):
            if chunk["type"] == "token":
                print(chunk["text"], end="", flush=True)
            elif chunk["type"] == "done":
                print("\n\n[done]")
            elif chunk["type"] == "blocked":
                print(f"\nBlocked: {chunk['text']}")
            elif chunk["type"] == "error":
                print(f"\nError: {chunk['text']}")