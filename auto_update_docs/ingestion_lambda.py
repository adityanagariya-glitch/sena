# auto_ingestion_lambda.py
# Triggered by EventBridge on S3 ObjectCreated events.
# Handles: metadata sidecar creation + ingestion job + registry tracking

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
ALLOWED_EXTENSIONS = (".pdf", ".docx")


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_org_id(s3_key: str) -> str | None:
    """
    Extracts org_id from S3 key path.
    e.g. sena/misty/orgs/org_sunrise/file.pdf → org_sunrise
         sena/misty/orgs/ndis/file.pdf        → ndis
    """
    if not s3_key.startswith(ORG_PREFIX):
        return None
    remainder = s3_key[len(ORG_PREFIX):]
    parts = remainder.split("/")
    if len(parts) < 2:
        return None
    return parts[0]


def is_allowed_file(s3_key: str) -> bool:
    """Only process PDF and DOCX — skip metadata sidecars and other files."""
    if s3_key.endswith(".metadata.json"):
        return False
    return s3_key.lower().endswith(ALLOWED_EXTENSIONS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Registry ──────────────────────────────────────────────────────────────────

def registry_create(doc_id: str, org_id: str, filename: str, bucket: str):
    """Creates a new registry entry with status INGESTING."""
    table = dynamodb.Table(REGISTRY_TABLE)
    table.put_item(Item={
        "doc_id":           doc_id,       # full S3 key — partition key
        "org_id":           org_id,
        "filename":         filename,
        "bucket":           bucket,
        "status":           "INGESTING",
        "uploaded_at":      now_iso(),
        "deleted_at":       None,
        "ingestion_job_id": None
    })
    logger.info(f"Registry: created entry for {doc_id} — status INGESTING")


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

    table.update_item(
        Key={"doc_id": doc_id},
        UpdateExpression="SET " + ", ".join(expressions),
        ExpressionAttributeValues=values,
        ExpressionAttributeNames=names
    )
    logger.info(f"Registry: updated {doc_id} → {updates}")


# ── Core Logic ────────────────────────────────────────────────────────────────

def create_metadata_sidecar(bucket: str, s3_key: str, org_id: str):
    """
    Creates .metadata.json sidecar next to the document in S3.
    Bedrock KB reads this during ingestion and attaches org_id
    to every chunk and embedding derived from this document.
    """
    metadata = {
        "metadataAttributes": {
            "org_id": org_id
        }
    }

    metadata_key = f"{s3_key}.metadata.json"

    s3.put_object(
        Bucket=bucket,
        Key=metadata_key,
        Body=json.dumps(metadata),
        ContentType="application/json"
    )

    logger.info(f"Metadata sidecar created: s3://{bucket}/{metadata_key}")


def run_ingestion_job(doc_id: str) -> str:
    """
    Starts a Bedrock KB ingestion job and polls until complete.
    Returns final status: COMPLETE or FAILED.
    """
    job = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId=DS_ID
    )

    job_id = job["ingestionJob"]["ingestionJobId"]
    logger.info(f"Ingestion job started: {job_id}")

    # Store job id in registry
    registry_update(doc_id, {"ingestion_job_id": job_id})

    # Poll until complete
    while True:
        response = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=KB_ID,
            dataSourceId=DS_ID,
            ingestionJobId=job_id
        )["ingestionJob"]

        status = response["status"]
        logger.info(f"Ingestion job {job_id} — status: {status}")

        if status == "COMPLETE":
            docs_indexed = response.get(
                "statistics", {}
            ).get("numberOfNewDocumentsIndexed", 0)
            logger.info(f"Ingestion complete — {docs_indexed} docs indexed")
            return "COMPLETE"

        elif status == "FAILED":
            failure_reasons = response.get("failureReasons", [])
            logger.error(f"Ingestion failed: {failure_reasons}")
            registry_update(doc_id, {"failure_reasons": str(failure_reasons)})
            return "FAILED"

        time.sleep(10)


# ── Handler ───────────────────────────────────────────────────────────────────

def handler(event, context):
    """
    Triggered by EventBridge on S3 ObjectCreated events.
    """
    logger.info(f"Event received: {json.dumps(event)}")

    try:
        detail   = event["detail"]
        bucket   = detail["bucket"]["name"]
        s3_key   = detail["object"]["key"]
        filename = s3_key.split("/")[-1]

    except KeyError as e:
        logger.error(f"Malformed event — missing key: {e}")
        return {"status": "ERROR", "reason": f"Malformed event: {e}"}

    # ── Guard: only orgs/ prefix ───────────────────────────────────────────
    if not s3_key.startswith(ORG_PREFIX):
        logger.info(f"Skipping — not in orgs/ prefix: {s3_key}")
        return {"status": "SKIPPED", "reason": "Not in orgs/ prefix"}

    # ── Guard: only PDF and DOCX ───────────────────────────────────────────
    if not is_allowed_file(s3_key):
        logger.info(f"Skipping — unsupported file type: {s3_key}")
        return {"status": "SKIPPED", "reason": "Unsupported file type"}

    # ── Extract org_id ─────────────────────────────────────────────────────
    org_id = extract_org_id(s3_key)
    if not org_id:
        logger.error(f"Could not extract org_id from key: {s3_key}")
        return {"status": "ERROR", "reason": "Could not extract org_id"}

    logger.info(f"Processing upload: {s3_key} | org_id: {org_id}")

    doc_id = s3_key

    # ── Step 1: Create registry entry ─────────────────────────────────────
    registry_create(doc_id, org_id, filename, bucket)

    # ── Step 2: Create metadata sidecar ───────────────────────────────────
    try:
        create_metadata_sidecar(bucket, s3_key, org_id)
    except Exception as e:
        logger.error(f"Failed to create metadata sidecar: {e}")
        registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
        return {"status": "ERROR", "reason": f"Metadata sidecar failed: {e}"}

    # ── Step 3: Run ingestion job ──────────────────────────────────────────
    try:
        final_status = run_ingestion_job(doc_id)
    except Exception as e:
        logger.error(f"Ingestion job error: {e}")
        registry_update(doc_id, {"status": "FAILED", "failure_reasons": str(e)})
        return {"status": "ERROR", "reason": f"Ingestion job failed: {e}"}

    # ── Step 4: Update registry with final status ──────────────────────────
    registry_update(doc_id, {"status": final_status})

    return {
        "status": final_status,
        "doc_id": doc_id,
        "org_id": org_id,
        "bucket": bucket
    }
