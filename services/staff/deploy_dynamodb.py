"""One-off setup: create a DynamoDB table for AgentCore session-id continuity.

The staff service caches a per-actor session_id so the same chat thread continues
across CLI / process restarts within a 24h window. Without a shared store, each
process or worker mints its own session_id for the same user — fragmenting the
AgentCore SUMMARY strategy and breaking "we talked about this earlier today".

Run once::

    python deploy_dynamodb.py   # uses REGION from config.py (ap-southeast-2)
    python deploy_dynamodb.py --region us-east-1

Run for table:

    python deploy_dynamodb.py   # default="SENA_AI_dynamodb_Memory_V2"
    python deploy_dynamodb.py --name "MyCustomTableName"

Idempotent: re-running on an existing table leaves the data alone and reports
the current state. After completion, paste the printed ``SENA_AI_SESSION_TABLE``
into your .env and restart the service — session storage will move from
``.memory_sessions.json`` to DynamoDB automatically.

Table shape::

    Partition key:  actor_id (S)        — composite "{org}_{user}"
    Attributes:     session_id, created_at, expires_at, ttl
    Native TTL:     enabled on `ttl` (90-day row retention, matches AgentCore)
    Billing:        PAY_PER_REQUEST (on-demand)

Cost note: single-key reads/writes are cheap (~$0.25/M reads, $1.25/M writes).
For a chatbot this rounds to cents/month — but tear it down if unused.
"""
import argparse
import sys
import time

import boto3
from botocore.exceptions import ClientError

from agents_types import DeploymentStatusResponse

try:
    from config import REGION as DEFAULT_REGION
except Exception:
    DEFAULT_REGION = "ap-southeast-2"


def _table_status(dynamodb, table_name: str) -> tuple[bool, str | None]:
    """Return (exists: bool, status: str|None) for the table."""
    try:
        resp = dynamodb.describe_table(TableName=table_name)
        return True, resp["Table"]["TableStatus"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False, None
        raise


def _ttl_status(dynamodb, table_name: str) -> str:
    """Return TTL status string ('ENABLED', 'ENABLING', 'DISABLED', 'DISABLING')."""
    try:
        resp = dynamodb.describe_time_to_live(TableName=table_name)
        return resp.get("TimeToLiveDescription", {}).get("TimeToLiveStatus", "DISABLED")
    except ClientError as e:
        print(f"[memory] describe_time_to_live failed: {e}", file=sys.stderr)
        return "UNKNOWN"


def deploy_session_table(region_name: str, table_name: str) -> None:
    """Create the session-id DynamoDB table with 90-day TTL — idempotent."""
    dynamodb = boto3.client("dynamodb", region_name=region_name)

    print(f"Region: {region_name}")
    print(f"Table:  {table_name}")

    exists, status = _table_status(dynamodb, table_name)
    if exists:
        print(f"Table '{table_name}' already exists (status={status}) — skipping create.")
    else:
        print(f"Creating table '{table_name}' (PK=actor_id, on-demand billing)…")
        try:
            dynamodb.create_table(
                TableName=table_name,
                KeySchema=[{"AttributeName": "actor_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "actor_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
                SSESpecification={"Enabled": True},
            )
        except ClientError as e:
            print(f"[memory] create_table failed: {e}", file=sys.stderr)
            raise

        print("Waiting for ACTIVE…")
        deadline = time.time() + 300  # 5-min cap
        while time.time() < deadline:
            _, status = _table_status(dynamodb, table_name)
            print(f"  status={status}")
            if status == "ACTIVE":
                break
            time.sleep(5)
        else:
            raise TimeoutError("Table did not reach ACTIVE within 5 minutes")

    # TTL is async; skip if already on, warn (not fatal) if enable fails.
    current_ttl = _ttl_status(dynamodb, table_name)
    if current_ttl in ("ENABLED", "ENABLING"):
        print(f"TTL already {current_ttl} on attribute 'ttl' — skipping.")
    else:
        print("Enabling TTL on attribute 'ttl' (90-day row retention)…")
        try:
            dynamodb.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
            )
            print("TTL enable requested (propagation can take up to 1 hour).")
        except ClientError as e:
            print(f"[memory] WARN: enable TTL failed: {e}", file=sys.stderr)
            print(f"[memory] WARN: table is usable, but rows will NOT auto-expire — "
                  f"rerun later or clean up manually.", file=sys.stderr)

    print()
    print(f"Done. Update your environment:")
    print(f"  SENA_AI_SESSION_TABLE={table_name}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--name", default="SENA_AI_dynamodb_Memory_V2")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (use in scripts).",
    )
    args = parser.parse_args()

    print("This will create (or verify) a DynamoDB table for session storage.")
    print(f"  region:    {args.region}")
    print(f"  name:      {args.name}")
    print(f"  PK:        actor_id (S)")
    print(f"  TTL:       enabled on `ttl` attribute (90-day row retention)")
    print(f"  billing:   PAY_PER_REQUEST")
    print()
    if not args.yes:
        confirm = input("Proceed? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted.")
            return 1

    deploy_session_table(args.region, args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
