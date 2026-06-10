"""
pipeline.py
-----------
Entry points for the document extraction module.

  run(file_path)      — local file path (used by tests and local CLI)
  run_from_s3(s3_key) — downloads from S3 then extracts (used by the API)

Both return ExtractionResult. The 5-field JSON contract is always honoured.
"""

import logging
import time
from pathlib import Path

from scripts.converter import detect_format, read_document
from scripts.extractor import extract
from scripts.models import ExtractionResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _failed_result(reason: str) -> ExtractionResult:
    """Build a fully-null ExtractionResult. Logs reason at ERROR level."""
    logger.error("Pipeline failed — %s", reason)
    return ExtractionResult()


def _log_summary(result: ExtractionResult, elapsed: float) -> None:
    logger.info(
        "Pipeline complete — filled=%d/5 elapsed=%.2fs missing=%s",
        5 - len(result.missing_fields()),
        elapsed,
        result.missing_fields() or "none",
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(file_path: str | Path) -> ExtractionResult:
    """
    Run the full extraction pipeline on a single document.

    Steps:
      1. Detect format and read raw bytes from disk.
      2. Send to Nova Lite via Bedrock (PDF/DOCX/image all handled natively).
      3. Parse and map response to 5 static fields.
      4. Return a validated ExtractionResult.

    The 5-field JSON contract is always honoured — even on failure.

    Args:
        file_path: Path to the uploaded document (.jpg, .jpeg, .png, .pdf, .docx).

    Returns:
        ExtractionResult — always.

    Raises:
        FileNotFoundError: File does not exist (caller error — not swallowed).
        ValueError:        Unsupported file extension (caller error — not swallowed).
    """
    file_path = Path(file_path)
    start = time.monotonic()

    logger.info("Pipeline started — file=%s", file_path.name)

    # Step 1 — read document (raises FileNotFoundError / ValueError to caller)
    try:
        raw_bytes, fmt, bedrock_fmt = read_document(file_path)
    except (FileNotFoundError, ValueError):
        raise
    except RuntimeError as exc:
        result = _failed_result(f"Read error: {exc}")
        _log_summary(result, time.monotonic() - start)
        return result

    # Step 2 — extract via Bedrock
    try:
        result = extract(raw_bytes, fmt, bedrock_fmt,
                         document_name=file_path.name, source="local")
    except (RuntimeError, ValueError) as exc:
        result = _failed_result(f"Extraction error: {exc}")

    _log_summary(result, time.monotonic() - start)
    return result


def run_from_s3(s3_key: str) -> ExtractionResult:
    """
    Download a document from S3 and run the full extraction pipeline.

    This is the entry point used by the production API endpoint (POST /extract).
    For local testing use run() instead, or call POST /extract/local.

    Steps:
      1. Download raw bytes from S3 using the object key.
      2. Detect format from the filename (extension).
      3. Send to Nova Lite via Bedrock.
      4. Return a validated ExtractionResult.

    Args:
        s3_key: S3 object key, e.g. "uploads/2024/passport.pdf"

    Returns:
        ExtractionResult — always.

    Raises:
        FileNotFoundError: S3 object does not exist.
        ValueError:        Unsupported file extension or S3_BUCKET_NAME not set.
    """
    from scripts.s3_client import download  # lazy import — only needed for S3 path

    start = time.monotonic()
    logger.info("Pipeline (S3) started — key=%s", s3_key)

    # Step 1 — download from S3
    try:
        raw_bytes, filename = download(s3_key)
    except (FileNotFoundError, ValueError):
        raise
    except RuntimeError as exc:
        result = _failed_result(f"S3 download error: {exc}")
        _log_summary(result, time.monotonic() - start)
        return result

    # Step 2 — detect format from filename extension (raises ValueError for unsupported)
    fmt, bedrock_fmt = detect_format(filename)

    # Step 3 — extract via Bedrock
    try:
        result = extract(raw_bytes, fmt, bedrock_fmt,
                         document_name=s3_key, source="s3")
    except (RuntimeError, ValueError) as exc:
        result = _failed_result(f"Extraction error: {exc}")

    _log_summary(result, time.monotonic() - start)
    return result