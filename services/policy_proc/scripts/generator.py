# generator.py
import boto3
import logging

from services.policy_proc.scripts.config import REGION, GENERATION_MODEL, MESSAGES
from services.policy_proc.scripts.prompt import SYSTEM_PROMPTS, ACTIVE_PROMPT_VERSION

logger = logging.getLogger(__name__)

bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION)


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
"""
    # Streaming generation
    try:
        response = bedrock_runtime.converse_stream(
            modelId=GENERATION_MODEL,
            system=[
                {
                    "text": SYSTEM_PROMPTS[ACTIVE_PROMPT_VERSION]
                }
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