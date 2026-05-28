# deploy_doc_lambdas.py
# Builds and deploys both ingestion and cleanup Lambdas to AWS.
# Run from project root: python deploy_doc_lambdas.py
#
# What it does:
#   1. Zips each Lambda script individually
#   2. Creates or updates the Lambda function on AWS
#   3. Sets environment variables
#   4. Verifies deployment
#
# No extra packages needed — both scripts only use boto3
# which is already built into the AWS Lambda Python runtime.

import boto3
import json
import zipfile
import os
import time

from scripts.config import REGION, KB_ID, DS_ID, REGISTRY_TABLE, BUCKET_NAME

lambda_client = boto3.client("lambda",  region_name=REGION)
iam           = boto3.client("iam")

# ── Config ────────────────────────────────────────────────────────────────────
RUNTIME   = "python3.12"
TIMEOUT   = 900    # 15 mins — ingestion jobs can take a while
MEMORY    = 256    # MB — these scripts are lightweight

LAMBDAS = [
    {
        "function_name": "sena-misty-auto-ingestion",
        "source_file":   "auto_update_docs/ingestion_lambda.py",
        "handler":       "ingestion_lambda.handler",
        "description":   "Auto-ingestion Lambda — triggered by S3 upload via EventBridge",
        "zip_name":      "ingestion_lambda.zip",
        "env_vars": {
            "KB_ID":          KB_ID,
            "DS_ID":          DS_ID,
            "REGISTRY_TABLE": REGISTRY_TABLE,
            "REGION":         REGION
        }
    },
    {
        "function_name": "sena-misty-cleanup",
        "source_file":   "auto_update_docs/cleanup_lambda.py",
        "handler":       "cleanup_lambda.handler",
        "description":   "Cleanup Lambda — triggered by S3 delete via EventBridge",
        "zip_name":      "cleanup_lambda.zip",
        "env_vars": {
            "KB_ID":          KB_ID,
            "DS_ID":          DS_ID,
            "REGISTRY_TABLE": REGISTRY_TABLE,
            "REGION":         REGION
        }
    }
]

ROLE_NAME = "sena-misty-doc-lambda-role"


# ── IAM Role ──────────────────────────────────────────────────────────────────

def get_or_create_role() -> str:
    """
    Creates IAM role for both Lambdas if it doesn't exist.
    Grants permissions to: S3, Bedrock KB, DynamoDB, CloudWatch logs.
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
        Description="Role for sena-misty ingestion and cleanup Lambdas"
    )
    role_arn = role["Role"]["Arn"]

    # Attach permissions
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
                # S3 — read docs + write/delete metadata sidecars
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket"
                ],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET_NAME}",
                    f"arn:aws:s3:::{BUCKET_NAME}/*"
                ]
            },
            {
                # Bedrock KB — start and monitor ingestion jobs
                "Effect": "Allow",
                "Action": [
                    "bedrock:StartIngestionJob",
                    "bedrock:GetIngestionJob",
                    "bedrock:ListIngestionJobs"
                ],
                "Resource": "*"
            },
            {
                # DynamoDB — read/write registry table
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query",
                    "dynamodb:Scan"
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:*:table/{REGISTRY_TABLE}",
                    f"arn:aws:dynamodb:{REGION}:*:table/{REGISTRY_TABLE}/index/*"
                ]
            }
        ]
    }

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="sena-misty-doc-lambda-policy",
        PolicyDocument=json.dumps(policy)
    )

    print(f"IAM role created: {role_arn}")
    print("Waiting 10s for IAM role to propagate...")
    time.sleep(10)

    return role_arn


# ── Build ─────────────────────────────────────────────────────────────────────

def build_zip(source_file: str, zip_name: str) -> bytes:
    """
    Zips the Lambda script.
    Returns zip bytes ready to upload to AWS.
    """
    print(f"  Building zip: {zip_name} from {source_file}")

    # Filename only — Lambda handler references just the filename without path
    filename = os.path.basename(source_file)

    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(source_file, filename)
        zf.write("scripts/config.py", "config.py")

    with open(zip_name, "rb") as f:
        zip_bytes = f.read()

    size_kb = len(zip_bytes) / 1024
    print(f"  Zip size: {size_kb:.1f} KB")

    # Clean up local zip file
    os.remove(zip_name)

    return zip_bytes


# ── Deploy ────────────────────────────────────────────────────────────────────

def deploy_lambda(config: dict, role_arn: str):
    """
    Creates or updates a Lambda function.
    If it already exists — updates code and config.
    If it doesn't exist — creates it fresh.
    """
    function_name = config["function_name"]
    print(f"\nDeploying: {function_name}")

    zip_bytes = build_zip(config["source_file"], config["zip_name"])

    try:
        # Try to get existing function
        lambda_client.get_function(FunctionName=function_name)
        exists = True
    except lambda_client.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        # Update code
        print(f"  Updating existing Lambda: {function_name}")
        lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=zip_bytes
        )
        # Wait for update to complete
        time.sleep(5)

        # Update config + env vars
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Timeout=TIMEOUT,
            MemorySize=MEMORY,
            Environment={"Variables": config["env_vars"]}
        )

    else:
        # Create fresh
        print(f"  Creating new Lambda: {function_name}")
        lambda_client.create_function(
            FunctionName=function_name,
            Runtime=RUNTIME,
            Role=role_arn,
            Handler=config["handler"],
            Code={"ZipFile": zip_bytes},
            Description=config["description"],
            Timeout=TIMEOUT,
            MemorySize=MEMORY,
            Environment={"Variables": config["env_vars"]}
        )
        # Wait for Lambda to become active
        print("  Waiting for Lambda to become active...")
        time.sleep(10)

    print(f"   {function_name} deployed")


def verify_lambda(function_name: str):
    """Reads back Lambda config to confirm deployment."""
    response = lambda_client.get_function_configuration(
        FunctionName=function_name
    )
    print(f"  State:    {response['State']}")
    print(f"  Runtime:  {response['Runtime']}")
    print(f"  Handler:  {response['Handler']}")
    print(f"  Timeout:  {response['Timeout']}s")
    print(f"  Memory:   {response['MemorySize']}MB")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Deploying sena-misty doc management Lambdas\n")

    # Step 1 — IAM role
    role_arn = get_or_create_role()

    # Step 2 — deploy each Lambda
    for config in LAMBDAS:
        deploy_lambda(config, role_arn)

    # Step 3 — verify
    print("\n── Verification ─────────────────────────────────────────────")
    for config in LAMBDAS:
        print(f"\n{config['function_name']}:")
        verify_lambda(config["function_name"])

    print("\n Both Lambdas deployed successfully")
    print("\nNext steps:")
    print("  1. Run setup_eventbridge_upload.py  — wires S3 upload → sena-misty-auto-ingestion")
    print("  2. Run setup_eventbridge_delete.py  — wires S3 delete → sena-misty-cleanup")


if __name__ == "__main__":
    main()
