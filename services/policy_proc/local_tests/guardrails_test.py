import boto3
import time
import json
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from scripts.prompt import SYSTEM_PROMPTS, ACTIVE_PROMPT_VERSION
from scripts.config import REGION, KB_ID, GUARDRAIL_ID, GUARDRAIL_VERSION, JUDGE_MODEL

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)
bedrock_runtime       = boto3.client("bedrock-runtime",       region_name=REGION)

ACTIVE_PROMPT_VERSION = "v1"

def query(question):
    print(f"\nQ: {question}")

    # Step 1: Retrieve
    retrieve_resp = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": 10}
        }
    )
    chunks   = [c["content"]["text"] for c in retrieve_resp["retrievalResults"]]
    context  = "\n\n".join(chunks)

    user_message = f"""Use the following policy context to answer the question.
Only use information explicitly stated in the context below.
Do not use any general NDIS knowledge outside of what is provided.
If the answer is not clearly in the context, say: "This isn't covered in the policies I have access to."

Context:
{context}

Question: {question}"""

    # Step 2: Generate with guardrail attached
    response = bedrock_runtime.converse(
        modelId=JUDGE_MODEL,
        system=[{"text": SYSTEM_PROMPTS[ACTIVE_PROMPT_VERSION]}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        guardrailConfig={
            "guardrailIdentifier": GUARDRAIL_ID,
            "guardrailVersion":    GUARDRAIL_VERSION,
            "trace":               "enabled"
        }
    )

    # Check if guardrail blocked
    stop_reason = response.get("stopReason", "")
    if stop_reason == "guardrail_intervened":
        print(" BLOCKED BY GUARDRAIL")
        print(f"A: {response['output']['message']['content'][0]['text']}")
    else:
        print(f" ANSWERED")
        print(f"A: {response['output']['message']['content'][0]['text']}")
 
# Test cases
time.sleep(5)
query("What is the safeguarding policy?")   
time.sleep(5)    
query("What is AWS?")  
time.sleep(5)                                 
query("What is privacy policy means?") 
