# cleanup_lambda.py
# Triggered by EventBridge on S3 ObjectRemoved events.
# Handles: metadata sidecar deletion + DELETE_NOT_FOUND ingestion job + registry update

import boto3
import json
import logging
import time
from datetime import datetime, timezone

from config import REGION, KB_ID, DS_ID, REGISTRY_TABLE, ORG_PREFIX

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Clients ───────────────────────────────────────────────────────────────────
s3            = boto3.client("s3",            region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)
dynamodb      = boto3.resource("dynamodb",    region_name=REGION)

# ── Config ────────────────────────────────────────────────────────────────────


# ── Helpers ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_org_id(s3_key: str) -> str | None:
    """
    Extracts org_id from S3 key path.
    e.g. sena/misty/orgs/org_sunrise/file.pdf → org_sunrise
    """
    if not s3_key.startswith(ORG_PREFIX):
        return None
    remainder = s3_key[len(ORG_PREFIX):]
    parts = remainder.split("/")
    if len(parts) < 2:
        return None
    return parts[0]


def is_document_file(s3_key: str) -> bool:
    """
    Only process actual documents — not metadata sidecars or other files.
    If a .metadata.json is deleted directly, skip it.
    """
    if s3_key.endswith(".metadata.json"):
        return False
    return s3_key.lower().endswith((".pdf", ".docx"))


# ── Registry ──────────────────────────────────────────────────────────────────

def registry_update(doc_id: str, updates: dict):
    """Updates specific fields on a registry entry."""
    table = dynamodb.Table(REGISTRY_TABLE)

    expressions = []
    values = {}
    names = {}

    for k, v in updates.items():
        safe_key = f"#f_{k}"
        val_key  = f":v_{k}"
        expressions.append(f"{safe_key} = {val_key}")
        values[val_key] = v
        names[safe_key] = k

    try:
        table.update_item(
            Key={"doc_id": doc_id},
            UpdateExpression="SET " + ", ".join(expressions),
            ExpressionAttributeValues=values,
            ExpressionAttributeNames=names
        )
        logger.info(f"Registry: updated {doc_id} → {updates}")
    except Exception as e:
        logger.error(f"Registry update failed for {doc_id}: {e}")


# ── Core Logic ────────────────────────────────────────────────────────────────

def delete_metadata_sidecar(bucket: str, s3_key: str):
    """
    Deletes the .metadata.json sidecar associated with the deleted document.
    If it doesn't exist (already deleted or never created) — safe to ignore.
    """
    metadata_key = f"{s3_key}.metadata.json"
    try:
        s3.delete_object(Bucket=bucket, Key=metadata_key)
        logger.info(f"Metadata sidecar deleted: s3://{bucket}/{metadata_key}")
    except Exception as e:
        logger.warning(f"Metadata sidecar not found or already deleted: {e}")


def run_cleanup_job(doc_id: str) -> str:
    """
    Starts a Bedrock KB ingestion job with DELETE_NOT_FOUND policy.
    Bedrock scans every vector, finds any whose source S3 file no longer
    exists, and deletes those vectors + chunks from S3 Vectors.
    Polls until complete. Returns final status: COMPLETE or FAILED.
    """
    job = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId=DS_ID,
        dataDeletionPolicy="DELETE_NOT_FOUND"
    )

    job_id = job["ingestionJob"]["ingestionJobId"]
    logger.info(f"Cleanup ingestion job started: {job_id}")

    # Store cleanup job id in registry
    registry_update(doc_id, {"cleanup_job_id": job_id})

    # Poll until complete
    while True:
        response = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=KB_ID,
            dataSourceId=DS_ID,
            ingestionJobId=job_id
        )["ingestionJob"]

        status = response["status"]
        logger.info(f"Cleanup job {job_id} — status: {status}")

        if status == "COMPLETE":
            docs_deleted = response.get(
                "statistics", {}
            ).get("numberOfDeletedDocuments", 0)
            logger.info(f"Cleanup complete — {docs_deleted} docs removed from index")
            return "COMPLETE"

        elif status == "FAILED":
            failure_reasons = response.get("failureReasons", [])
            logger.error(f"Cleanup job failed: {failure_reasons}")
            registry_update(doc_id, {"failure_reasons": str(failure_reasons)})
            return "FAILED"

        time.sleep(10)


# ── Handler ───────────────────────────────────────────────────────────────────

def handler(event, context):
    """
    Triggered by EventBridge on S3 ObjectRemoved events.
    """
    logger.info(f"Event received: {json.dumps(event)}")

    try:
        detail = event["detail"]
        bucket = detail["bucket"]["name"]
        s3_key = detail["object"]["key"]

    except KeyError as e:
        logger.error(f"Malformed event — missing key: {e}")
        return {"status": "ERROR", "reason": f"Malformed event: {e}"}

    # ── Guard: only orgs/ prefix ───────────────────────────────────────────
    if not s3_key.startswith(ORG_PREFIX):
        logger.info(f"Skipping — not in orgs/ prefix: {s3_key}")
        return {"status": "SKIPPED", "reason": "Not in orgs/ prefix"}

    # ── Guard: only actual documents, not sidecars ─────────────────────────
    if not is_document_file(s3_key):
        logger.info(f"Skipping — not a document file: {s3_key}")
        return {"status": "SKIPPED", "reason": "Not a document file"}

    # ── Extract org_id ─────────────────────────────────────────────────────
    org_id = extract_org_id(s3_key)
    if not org_id:
        logger.error(f"Could not extract org_id from key: {s3_key}")
        return {"status": "ERROR", "reason": "Could not extract org_id"}

    logger.info(f"Processing delete: {s3_key} | org_id: {org_id}")

    doc_id = s3_key

    # ── Step 1: Mark registry as DELETING ─────────────────────────────────
    registry_update(doc_id, {"status": "DELETING"})

    # ── Step 2: Delete metadata sidecar ───────────────────────────────────
    delete_metadata_sidecar(bucket, s3_key)

    # ── Step 3: Run cleanup ingestion job ─────────────────────────────────
    try:
        final_status = run_cleanup_job(doc_id)
    except Exception as e:
        logger.error(f"Cleanup job error: {e}")
        registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
        return {"status": "ERROR", "reason": f"Cleanup job failed: {e}"}

    # ── Step 4: Update registry — permanent record, no TTL ────────────────
    registry_update(doc_id, {
        "status":     "DELETED",
        "deleted_at": now_iso()
    })

    return {
        "status": final_status,
        "doc_id": doc_id,
        "org_id": org_id,
        "bucket": bucket
    }
