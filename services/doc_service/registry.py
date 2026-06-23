import boto3
import logging
from datetime import datetime, timezone

from config import REGION, REGISTRY_TABLE

logger = logging.getLogger(__name__)

dynamodb = boto3.resource("dynamodb", region_name=REGION)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def registry_create(doc_id: str, org_id: str, filename: str, bucket: str):
    table = dynamodb.Table(REGISTRY_TABLE)
    table.put_item(Item={
        "doc_id":           doc_id,
        "org_id":           org_id,
        "filename":         filename,
        "bucket":           bucket,
        "status":           "INGESTING",
        "uploaded_at":      now_iso(),
        "deleted_at":       None,
        "ingestion_job_id": None,
        "cleanup_job_id":   None,
        "failure_reasons":  None,
    })
    logger.info(f"Registry: created {doc_id} — INGESTING")


def registry_update(doc_id: str, updates: dict):
    table = dynamodb.Table(REGISTRY_TABLE)
    expressions, values, names = [], {}, {}
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
            ExpressionAttributeNames=names,
        )
        logger.info(f"Registry: updated {doc_id} → {updates}")
    except Exception as e:
        logger.error(f"Registry update failed for {doc_id}: {e}")


def registry_get(doc_id: str) -> dict | None:
    table = dynamodb.Table(REGISTRY_TABLE)
    try:
        return table.get_item(Key={"doc_id": doc_id}).get("Item")
    except Exception as e:
        logger.error(f"Registry get failed for {doc_id}: {e}")
        return None


def registry_list_by_org(org_id: str) -> list:
    table = dynamodb.Table(REGISTRY_TABLE)
    try:
        resp = table.query(
            IndexName="org_id-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("org_id").eq(org_id),
        )
        return resp.get("Items", [])
    except Exception as e:
        logger.error(f"Registry list failed for org {org_id}: {e}")
        return []
