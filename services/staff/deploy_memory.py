"""One-off setup: create a new AgentCore Memory with extraction strategies.

Strategies are immutable on an existing memory resource, so this script creates
a brand-new memory configured with USER_PREFERENCE + SEMANTIC + SUMMARY and
prints the new memoryId for you to paste into ``SENA_AI_AGENTCORE_MEMORY_ID``.

Run once:
    python deploy_memory.py  # uses REGION from config.py (ap-southeast-2)
    python deploy_memory.py --region us-east-1

Run for memory :
    python deploy_memory.py   # default="SENA_AI_AgentCore_Memory_V2"
    python deploy_memory.py --name "MyCustomMemoryName"

This does NOT delete or migrate the existing memory — the old one keeps its
short-term events until its own TTL expires. Update the env var and restart
the service to start writing turns into the new strategy-enabled memory.

Cost note: AgentCore Memory bills per active memory + per stored record. Don't
spin these up casually — keep the one you actually use.
"""
import argparse
import sys
import time

import boto3
from botocore.exceptions import ClientError

from agents_types import DeploymentStatusResponse

# Reuse the project's region default
try:
    from config import REGION as DEFAULT_REGION
except Exception:
    DEFAULT_REGION = "ap-southeast-2"


def deploy_strategy_enabled_memory(region_name: str, memory_name: str, description: str, event_expiry_days: int) -> str | None:
    """Create a new memory resource with USER_PREFERENCE + SEMANTIC + SUMMARY strategies."""
    control_client = boto3.client("bedrock-agentcore-control", region_name=region_name)

    # 2026 control-plane payload shape. The {actorId}/{sessionId} tokens are
    # template placeholders interpreted server-side — do NOT format() them.
    memory_strategies = [
        {
            "userPreferenceMemoryStrategy": {
                "name": "UserPreferenceExtractor",
                "namespaceTemplates": ["/users/{actorId}/preferences/"],
            }
        },
        {
            "semanticMemoryStrategy": {
                "name": "FactAndKnowledgeExtractor",
                "namespaceTemplates": ["/users/{actorId}/facts/"],
            }
        },
        {
            "summaryMemoryStrategy": {
                "name": "RollingSessionSummarizer",
                "namespaceTemplates": ["/summaries/{actorId}/{sessionId}/"],
            }
        },
    ]

    print(f"Region: {region_name}")
    print(f"Creating memory '{memory_name}' with 3 extraction strategies "
          f"(raw event retention: {event_expiry_days} days)…")

    try:
        # eventExpiryDuration controls how long raw turn events are kept before
        # purge. Extracted long-term memories (preferences, facts, summaries)
        # are NOT affected by this — they live independently.
        response = control_client.create_memory(
            name=memory_name,
            description=description,
            eventExpiryDuration=event_expiry_days,
            memoryStrategies=memory_strategies,
        )
    except ClientError as e:
        print(f"Failed to create memory: {e}", file=sys.stderr)
        raise

    new_memory_id = response["memory"]["id"]
    print(f"Created memoryId={new_memory_id} — waiting for ACTIVE…")

    deadline = time.time() + 600  # 10-min cap
    while time.time() < deadline:
        try:
            status_response = control_client.get_memory(memoryId=new_memory_id)
        except ClientError as e:
            print(f"get_memory failed: {e}", file=sys.stderr)
            raise

        current_status = status_response.get("memory", {}).get("status")
        print(f"  status={current_status}")

        if current_status == "ACTIVE":
            print()
            print(f"ACTIVE. Update your environment:")
            print(f"  SENA_AI_AGENTCORE_MEMORY_ID={new_memory_id}")
            print()
            return new_memory_id

        if current_status == "FAILED":
            failure = status_response.get("memory", {}).get("failureReason", "unknown")
            raise RuntimeError(f"Memory provisioning FAILED: {failure}")

        time.sleep(15)

    raise TimeoutError("Memory did not reach ACTIVE within 10 minutes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--name", default="SENA_AI_AgentCore_Memory_V2")
    parser.add_argument(
        "--description",
        default="SENA NDIS assistant memory — USER_PREFERENCE + SEMANTIC + SUMMARY strategies.",
    )
    parser.add_argument(
        "--event-expiry-days",
        type=int,
        default=90,
        help="How many days to retain raw turn events before purge (1-365). "
             "Long-term extracted memories are unaffected. Default: 90.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (use in scripts).",
    )
    args = parser.parse_args()

    if not (1 <= args.event_expiry_days <= 365):
        print("--event-expiry-days must be between 1 and 365.", file=sys.stderr)
        return 2

    print("This will create a NEW AgentCore Memory resource in AWS.")
    print(f"  region:           {args.region}")
    print(f"  name:             {args.name}")
    print(f"  strategies:       USER_PREFERENCE, SEMANTIC, SUMMARY")
    print(f"  event retention:  {args.event_expiry_days} days")
    print()
    if not args.yes:
        confirm = input("Proceed? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted.")
            return 1

    deploy_strategy_enabled_memory(
        args.region,
        args.name,
        args.description,
        args.event_expiry_days,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
