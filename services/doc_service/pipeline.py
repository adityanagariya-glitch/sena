"""
Document pipeline — upload and delete flows.

Upload:  raw bytes → S3 raw → .md conversion → S3 md + sidecar → registry → KB ingestion
Delete:  S3 raw + md + sidecar → KB document delete → registry DELETED
"""
import json
import logging
import os
import tempfile
import time

import boto3
import httpx
from markitdown import MarkItDown

from config import (
    REGION, BUCKET_NAME, ORG_PREFIX, MD_PREFIX,
    KB_ID, DS_ID, POLL_INTERVAL_SECONDS, POLL_MAX_ATTEMPTS,
    SOURCE_BUCKET,
)
from registry import registry_create, registry_update, now_iso

logger = logging.getLogger(__name__)

s3            = boto3.client("s3",            region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)
md_converter  = MarkItDown()

SUPPORTED_EXTENSIONS = {
    ".pdf", ".txt", ".md",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".csv", ".html", ".htm",
}


# ── Upload helpers ────────────────────────────────────────────────────────────

def _upload_raw(file_bytes: bytes, filename: str, org_id: str) -> str:
    raw_key = f"{ORG_PREFIX}{org_id}/{filename}"
    s3.put_object(Bucket=BUCKET_NAME, Key=raw_key, Body=file_bytes)
    logger.info(f"Uploaded raw: {raw_key}")
    return raw_key


def _convert_and_upload_md(file_bytes: bytes, filename: str, org_id: str) -> str:
    ext       = os.path.splitext(filename)[1].lower()
    base_name = os.path.splitext(filename)[0]
    md_key    = f"{MD_PREFIX}{org_id}/{base_name}.md"

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        result   = md_converter.convert(tmp_path)
        md_bytes = result.text_content.encode("utf-8")
    finally:
        os.unlink(tmp_path)

    s3.put_object(Bucket=BUCKET_NAME, Key=md_key, Body=md_bytes, ContentType="text/markdown")
    logger.info(f"Uploaded .md: {md_key}")
    return md_key


def _upload_sidecar(md_key: str, org_id: str, doc_type: str):
    sidecar_key  = f"{md_key}.metadata.json"
    sidecar_body = json.dumps({
        "metadataAttributes": {"org_id": org_id, "doc_type": doc_type}
    })
    s3.put_object(
        Bucket=BUCKET_NAME, Key=sidecar_key,
        Body=sidecar_body.encode("utf-8"), ContentType="application/json",
    )
    logger.info(f"Uploaded sidecar: {sidecar_key}")


def _start_kb_ingestion() -> str:
    resp   = bedrock_agent.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)
    job_id = resp["ingestionJob"]["ingestionJobId"]
    logger.info(f"KB ingestion job started: {job_id}")
    return job_id


# ── Upload background task ────────────────────────────────────────────────────

def poll_and_update(doc_id: str, job_id: str):
    """
    Background task: poll KB ingestion job until COMPLETE or FAILED,
    then update registry. Called after 202 is sent to frontend.
    """
    for attempt in range(POLL_MAX_ATTEMPTS):
        try:
            resp   = bedrock_agent.get_ingestion_job(
                knowledgeBaseId=KB_ID, dataSourceId=DS_ID, ingestionJobId=job_id,
            )
            status = resp["ingestionJob"]["status"]

            if status == "COMPLETE":
                registry_update(doc_id, {"status": "COMPLETE", "ingestion_job_id": job_id})
                logger.info(f"Ingestion COMPLETE: {doc_id}")
                return

            if status == "FAILED":
                reasons = str(resp["ingestionJob"].get("failureReasons", []))
                registry_update(doc_id, {
                    "status": "FAILED", "ingestion_job_id": job_id, "failure_reasons": reasons,
                })
                logger.error(f"Ingestion FAILED: {doc_id} — {reasons}")
                return

        except Exception as e:
            logger.warning(f"Poll attempt {attempt + 1} error: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)

    registry_update(doc_id, {"status": "FAILED", "failure_reasons": "Ingestion polling timed out"})
    logger.error(f"Ingestion polling timed out: {doc_id}")


# ── Source fetch (partner S3 key or CDN URL) ──────────────────────────────────

def _fetch_from_source(s3_key: str, cdn_url: str | None) -> bytes:
    """
    Retrieve file bytes from the partner's storage.
    Prefers cdn_url (HTTP GET) when provided; falls back to cross-account
    S3 read using SOURCE_BUCKET if configured.
    """
    if cdn_url:
        resp = httpx.get(cdn_url, follow_redirects=True, timeout=60.0)
        if resp.status_code != 200:
            raise ValueError(f"CDN fetch returned HTTP {resp.status_code}: {cdn_url}")
        return resp.content

    if not SOURCE_BUCKET:
        raise ValueError(
            "cdn_url was not provided and SOURCE_BUCKET is not configured — "
            "cannot fetch source file"
        )
    obj = s3.get_object(Bucket=SOURCE_BUCKET, Key=s3_key)
    return obj["Body"].read()


# ── S3-key ingestion entrypoint ───────────────────────────────────────────────

def run_ingest_from_key(
    s3_key:   str,
    org_id:   str,
    doc_type: str,
    cdn_url:  str | None = None,
) -> tuple[str, str]:
    """
    Ingestion pipeline triggered by a partner server — no file upload required.
      1. Fetch file bytes from partner's CDN URL or S3 key
      2. Convert to .md, upload to our S3
      3. Upload metadata sidecar
      4. Write registry entry (status: INGESTING, ingestion_source: s3_key)
      5. Start KB ingestion job
    Returns (doc_id, job_id). Caller adds poll_and_update as a BackgroundTask.
    """
    filename = s3_key.split("/")[-1]
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")

    file_bytes = _fetch_from_source(s3_key, cdn_url)
    if not file_bytes:
        raise ValueError("Fetched document is empty")

    md_key = None
    try:
        md_key = _convert_and_upload_md(file_bytes, filename, org_id)
        _upload_sidecar(md_key, org_id, doc_type)
    except Exception:
        if md_key:
            _safe_delete_s3(md_key)
        raise

    doc_id = md_key
    registry_create(
        doc_id=doc_id,
        org_id=org_id,
        filename=filename,
        bucket=BUCKET_NAME,
        source_s3_key=s3_key,
        ingestion_source="s3_key",
    )

    job_id = _start_kb_ingestion()
    registry_update(doc_id, {"ingestion_job_id": job_id})
    return doc_id, job_id


# ── Upload entrypoint ─────────────────────────────────────────────────────────

def run_upload(
    file_bytes: bytes,
    filename:   str,
    org_id:     str,
    doc_type:   str,
) -> tuple[str, str]:
    """
    Synchronous steps (runs before 202 response):
      1. Upload raw to S3
      2. Convert to .md, upload to S3
      3. Upload metadata sidecar
      4. Write registry entry (status: INGESTING)
      5. Start KB ingestion job
    Returns (doc_id, job_id).
    Caller adds poll_and_update as a BackgroundTask.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")

    raw_key = _upload_raw(file_bytes, filename, org_id)
    try:
        md_key = _convert_and_upload_md(file_bytes, filename, org_id)
        _upload_sidecar(md_key, org_id, doc_type)
    except Exception:
        _safe_delete_s3(raw_key)
        raise

    doc_id = md_key  # doc_id == .md S3 key (what lives in KB)
    registry_create(doc_id=doc_id, org_id=org_id, filename=filename, bucket=BUCKET_NAME)

    job_id = _start_kb_ingestion()
    registry_update(doc_id, {"ingestion_job_id": job_id})
    return doc_id, job_id


# ── Delete helpers ────────────────────────────────────────────────────────────

def _safe_delete_s3(key: str):
    """Delete a single S3 object. Logs warning on failure, never raises."""
    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=key)
        logger.info(f"Deleted from S3: {key}")
    except Exception as e:
        logger.warning(f"S3 delete failed for {key}: {e}")


def _delete_from_kb(md_key: str) -> bool:
    """
    Explicitly remove a document from the Bedrock KB index
    using delete_knowledge_base_documents.
    Returns True on success, False on failure.
    """
    try:
        bedrock_agent.delete_knowledge_base_documents(
            knowledgeBaseId=KB_ID,
            dataSourceId=DS_ID,
            documentIdentifiers=[{
                "dataSourceType": "S3",
                "s3": {"uri": f"s3://{BUCKET_NAME}/{md_key}"}
            }],
        )
        logger.info(f"Deleted from KB index: {md_key}")
        return True
    except Exception as e:
        logger.error(f"KB document delete failed for {md_key}: {e}")
        return False


# ── Delete background task ────────────────────────────────────────────────────

def run_delete(doc_id: str, org_id: str, filename: str, ingestion_source: str = "direct_upload"):
    """
    Background task (runs after 202 is sent to frontend):
      1. Delete .md from S3
      2. Delete sidecar from S3
      3. Remove document from KB index
      4. Update registry → DELETED
    Raw S3 file is intentionally NOT deleted.
    doc_id == .md S3 key (e.g. sena/misty/md/orgs/org_sunrise/policy.md)
    """
    sidecar_key = f"{doc_id}.metadata.json"
    _safe_delete_s3(doc_id)
    _safe_delete_s3(sidecar_key)
    kb_deleted = _delete_from_kb(doc_id)

    updates = {"status": "DELETED", "deleted_at": now_iso()}
    if not kb_deleted:
        updates["failure_reasons"] = "KB index removal failed — vectors may still be queryable"
    registry_update(doc_id, updates)
    logger.info(f"Delete complete: {doc_id}")
