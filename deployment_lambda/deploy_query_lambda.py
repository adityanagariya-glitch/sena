# deploy_query_lambda.py
# Builds and deploys the query handler Lambda (sena-misty-query-handler).
# Packages all scripts/ files + installs dependencies into a zip.
#
# Run from project root:
#   python deploy_query_lambda.py

import boto3
import json
import os
import shutil
import subprocess
import zipfile
import time

from scripts.config import (
    REGION,
    KB_ID,
    DS_ID,
    GUARDRAIL_ID,
    GUARDRAIL_VERSION,
    MEMORY_ID,
    NUM_RESULTS,
    RERANK_TOP,
    BUCKET_NAME,
    GENERATION_MODEL,
    CLASSIFIER_MODEL,
    RERANKER_MODEL,
    SESSIONS_TABLE,
    TURNS_TABLE,
)

lambda_client = boto3.client("lambda", region_name=REGION)
iam           = boto3.client("iam")

# ── Config ────────────────────────────────────────────────────────────────────
FUNCTION_NAME = "sena-misty-query-handler"
RUNTIME       = "python3.12"
HANDLER       = "lambda_function.handler"
TIMEOUT       = 60      # seconds — RAG pipeline takes 10-15s
MEMORY        = 512     # MB
ROLE_NAME     = "sena-misty-query-lambda-role"
BUILD_DIR     = "lambda_build"
ZIP_FILE      = "query_lambda_package.zip"

# All scripts to include — flattened into Lambda root
SCRIPT_FILES = [
    "scripts/lambda_function.py",
    "scripts/pipeline.py",
    "scripts/classifier.py",
    "scripts/retriever.py",
    "scripts/generator.py",
    "scripts/memory.py",
    "scripts/rewriter.py",
    "scripts/config.py",
    "scripts/prompt.py",
]

# Environment variables Lambda reads at runtime
ENV_VARS = {
    "ENV":              "prod",
    "KB_ID":            KB_ID,
    "DS_ID":            DS_ID,
    "GUARDRAIL_ID":     GUARDRAIL_ID,
    "GUARDRAIL_VERSION":GUARDRAIL_VERSION,
    "MEMORY_ID":        MEMORY_ID,
    "REGION":           REGION,
    "NUM_RESULTS":      str(NUM_RESULTS),
    "RERANK_TOP":       str(RERANK_TOP),
    "BUCKET_NAME":      BUCKET_NAME,
    "GENERATION_MODEL": GENERATION_MODEL,
    "CLASSIFIER_MODEL": CLASSIFIER_MODEL,
    "RERANKER_MODEL":   RERANKER_MODEL,
    "SESSIONS_TABLE":   SESSIONS_TABLE,
    "TURNS_TABLE":      TURNS_TABLE
}


# ── IAM Role ──────────────────────────────────────────────────────────────────

def get_or_create_role() -> str:
    """
    Creates IAM role for the query Lambda if it doesn't exist.
    Grants permissions to: Bedrock KB, Bedrock runtime, DynamoDB,
    AgentCore Memory, CloudWatch logs.
    Returns role ARN.
    """
    try:
        role = iam.get_role(RoleName=ROLE_NAME)
        print(f"IAM role exists: {role['Role']['Arn']}")
        return role["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass

    print("Creating IAM role...")

    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }

    role = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust),
        Description="Role for sena-misty query handler Lambda"
    )
    role_arn = role["Role"]["Arn"]

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                # CloudWatch logs
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            },
            {
                # Bedrock — invoke models + KB retrieval
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                    "bedrock:ApplyGuardrail"
                ],
                "Resource": "*"
            },
            {
                # Bedrock agent runtime — KB retrieve
                "Effect": "Allow",
                "Action": [
                    "bedrock:Retrieve"
                ],
                "Resource": f"arn:aws:bedrock:{REGION}:*:knowledge-base/*"
            },
            {
                # DynamoDB — sessions and turns tables
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:DeleteItem"
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-dev-chat-sessions",
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-dev-chat-turns",
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-prod-chat-sessions",
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-prod-chat-turns",
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-dev-chat-sessions/index/*",
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-dev-chat-turns/index/*",
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-prod-chat-sessions/index/*",
                    f"arn:aws:dynamodb:{REGION}:*:table/sena-prod-chat-turns/index/*"
                ]
            },
            {
                # AgentCore Memory
                "Effect": "Allow",
                "Action": [
                    "bedrock:CreateEvent",
                    "bedrock:RetrieveMemoryRecords",
                    "bedrock:GetMemory"
                ],
                "Resource": "*"
            }
        ]
    }

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="sena-misty-query-lambda-policy",
        PolicyDocument=json.dumps(policy)
    )

    print(f"IAM role created: {role_arn}")
    print("Waiting 10s for IAM role to propagate...")
    time.sleep(10)

    return role_arn


# ── Build ─────────────────────────────────────────────────────────────────────

def build_zip() -> bytes:
    """
    Packages all scripts + dependencies into a zip.
    boto3 is excluded — already in Lambda runtime.
    Returns zip bytes ready to upload to AWS.
    """
    print("\nBuilding Lambda package...")

    # Clean build dir
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR)

    # Install dependencies — exclude boto3 (built into Lambda runtime)
    print("  Installing dependencies...")
    subprocess.run([
        "pip", "install",
        "strands-agents",
        "strands-agents-tools",
        "--target", BUILD_DIR,
        "--quiet",
        "--no-deps"
    ], check=False)   # check=False — ok if strands not needed, boto3 not installed

    # Copy script files — flatten into Lambda root (no scripts/ prefix)
    print("  Copying source files...")
    for filepath in SCRIPT_FILES:
        if not os.path.exists(filepath):
            print(f"  WARNING: {filepath} not found — skipping")
            continue
        filename = os.path.basename(filepath)
        shutil.copy(filepath, os.path.join(BUILD_DIR, filename))
        print(f"    Copied: {filename}")

    # Zip everything
    print("  Creating zip...")
    if os.path.exists(ZIP_FILE):
        os.remove(ZIP_FILE)

    with zipfile.ZipFile(ZIP_FILE, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(BUILD_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for file in files:
                filepath = os.path.join(root, file)
                arcname  = os.path.relpath(filepath, BUILD_DIR)
                zf.write(filepath, arcname)

    # Clean up build dir
    shutil.rmtree(BUILD_DIR)

    with open(ZIP_FILE, "rb") as f:
        zip_bytes = f.read()

    size_mb = len(zip_bytes) / (1024 * 1024)
    print(f"  Package size: {size_mb:.1f} MB")

    # Clean up zip file
    os.remove(ZIP_FILE)

    return zip_bytes


# ── Deploy ────────────────────────────────────────────────────────────────────

def deploy(role_arn: str, zip_bytes: bytes):
    """Creates or updates the query handler Lambda."""
    print(f"\nDeploying: {FUNCTION_NAME}")

    try:
        lambda_client.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except lambda_client.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        print("  Updating existing Lambda...")
        lambda_client.update_function_code(
            FunctionName=FUNCTION_NAME,
            ZipFile=zip_bytes
        )
        time.sleep(5)

        lambda_client.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Timeout=TIMEOUT,
            MemorySize=MEMORY,
            Environment={"Variables": ENV_VARS}
        )

    else:
        print("  Creating new Lambda...")
        lambda_client.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime=RUNTIME,
            Role=role_arn,
            Handler=HANDLER,
            Code={"ZipFile": zip_bytes},
            Description="SENA RAG query handler — classifier → rewriter → retriever → generator",
            Timeout=TIMEOUT,
            MemorySize=MEMORY,
            Environment={"Variables": ENV_VARS}
        )
        print("  Waiting for Lambda to become active...")
        time.sleep(10)

    print(f"  ✅ {FUNCTION_NAME} deployed")


def verify():
    """Reads back Lambda config to confirm deployment."""
    print("\n── Verification ─────────────────────────────────────────────")
    response = lambda_client.get_function_configuration(
        FunctionName=FUNCTION_NAME
    )
    print(f"Function:  {response['FunctionName']}")
    print(f"State:     {response['State']}")
    print(f"Runtime:   {response['Runtime']}")
    print(f"Handler:   {response['Handler']}")
    print(f"Timeout:   {response['Timeout']}s")
    print(f"Memory:    {response['MemorySize']}MB")
    print(f"Env vars:  {list(response['Environment']['Variables'].keys())}")
    print("─────────────────────────────────────────────────────────────")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Deploying {FUNCTION_NAME}\n")

    # Step 1 — IAM role
    role_arn = get_or_create_role()

    # Step 2 — build zip
    zip_bytes = build_zip()

    # Step 3 — deploy
    deploy(role_arn, zip_bytes)

    # Step 4 — verify
    verify()

    print(f"\n {FUNCTION_NAME} ready")
    print("\nNext steps:")
    print("  1. Set up API Gateway to point to this Lambda")
    print("  2. Update FastAPI to call API Gateway instead of pipeline.py directly")
    print("  3. Test end to end via Streamlit")


if __name__ == "__main__":
    main()
