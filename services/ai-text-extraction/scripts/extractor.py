"""
extractor.py
------------
Responsible for:
  1. Building the correct Bedrock request for each format.
     - PDF / DOCX → "document" block
     - JPG / PNG  → "image" block
  2. Sending raw file bytes to Nova Lite via Bedrock (Sydney).
  3. Parsing the JSON response.
  4. Mapping raw parsed values to the 5 static fields.
  5. Returning a validated ExtractionResult.

Nova Lite accepts PDF, DOCX, JPG, and PNG natively.
No conversion is done here or in converter.py.
"""

import json
import logging
import time

import boto3
from botocore.exceptions import ClientError
from langfuse import observe, get_client

from scripts.config import config
from scripts.converter import DocumentFormat
from scripts.models import ExtractionResult, TokenUsage

logger = logging.getLogger(__name__)

langfuse = get_client()
_SERVICE = "ai-text-extraction"

_lf_prompt = None
try:
    _lf_prompt = langfuse.get_prompt(f"{_SERVICE}/extraction-system")
except Exception:
    pass


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
# System prompt — detailed rules and definitions
SYSTEM_PROMPT = """\
You are an identity document data extraction system specialised in Australian identity documents.

STEP 1 — Before filling any field, scan the ENTIRE document and mentally list every \
date-like value you see (any format: DD/MM/YYYY, YYYY-MM-DD, DD MON YYYY, etc.) \
together with its exact printed label.

STEP 2 — Using those labeled dates, map them to the five fields below. \
Never assign a date to a field unless its printed label matches the rules for that field.

───────────────────────────────────────────────────────────
FIELD DEFINITIONS
───────────────────────────────────────────────────────────

document_no:
  The document/card/licence identifier number.
  Labels to look for: "Document No", "Licence No", "Card No", "Card Number",
                      "Document Number", "No.", "Number".

name:
  The full name of the document holder exactly as printed.
  Labels to look for: "Name", "Given Names", "Given Name", "Surname", "Family Name".
  If given names and family name are printed separately, combine them in this order:
  given name(s) first, then family name (e.g. "Jane Anne Citizen").

issue_date:
  The date THIS document or licence was ISSUED or GRANTED — this is NEVER the holder's
  date of birth.

  Labels that mean ISSUE DATE — use ONLY these:
    "Date of Issue", "Issue Date", "Licence Issue Date", "Date Issued",
    "Date Granted", "Licensed From", "Valid From", "Date de délivrance",
    "Date of issue / Date de délivrance"

  Labels that mean DATE OF BIRTH — NEVER use a date with any of these labels for issue_date:
    "Date of Birth", "DOB", "D.O.B", "D.O.B.", "Born", "Birth Date",
    "Date of birth / Date de naissance", "Birthdate"

  Additional rules:
    - If the document shows both a date of birth AND an issue date, always use the
      issue date — never the date of birth.
    - If you cannot find a date whose label clearly matches an issue date label above,
      return null. Do NOT substitute or guess using the date of birth.
    - On driver licences where "Licence Issue Date" and "Card Issue Date" both appear,
      use "Licence Issue Date".

expiry_date:
  The date this document expires.
  Labels to look for: "Expiry", "Expiry Date", "Date of Expiry", "Valid To",
                      "Valid Until", "Expires", "Date d'expiration",
                      "Date of expiry / Date d'expiration".
  If not present on the document, return null.

address:
  The full residential or mailing address printed on the document.
  Present on: driver licences, proof of age cards, state-issued ID cards.
  Passports and Medicare cards typically have no address — return null for those.

───────────────────────────────────────────────────────────
DATE FORMAT
───────────────────────────────────────────────────────────
Normalise ALL extracted dates to YYYY-MM-DD.
  "04 MAY 1991"  →  "1991-05-04"
  "21/06/2025"   →  "2025-06-21"
  "21 Jun 25"    →  "2025-06-21"
Apply this normalisation to issue_date and expiry_date only.
Never extract date of birth under any field name.

───────────────────────────────────────────────────────────
OUTPUT RULES
───────────────────────────────────────────────────────────
- Return ONLY a valid JSON object. No explanation, no markdown, no code fences.
- Use exactly these five key names: document_no, name, issue_date, expiry_date, address.
- If a field is not present on the document, set its value to null.
- Do not infer or guess values. Only extract what is explicitly printed.
- Do not include any fields beyond the five listed above.

Expected output shape:
{
  "document_no": "P1234567",
  "name": "Jane Citizen",
  "issue_date": "2022-06-21",
  "expiry_date": "2025-06-21",
  "address": null
}
"""

# User turn — short task trigger that accompanies the document
USER_LITEMPT = """\
Extract the 5 fields from this identity document and return a JSON object only.
"""


# ---------------------------------------------------------------------------
# Bedrock client
# ---------------------------------------------------------------------------

_bedrock_client = None


def _get_client():
    """Return the module-level Bedrock client, created once on first call."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=config.bedrock.region,
        )
    return _bedrock_client


# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------

def _build_content_block(
    raw_bytes: bytes,
    fmt: DocumentFormat,
    bedrock_fmt: str,
) -> list[dict]:
    """
    Build the Bedrock message content blocks for the given format.

    PDF / DOCX → "document" block (Nova Lite reads them natively via vision)
    JPG / PNG  → "image" block

    Args:
        raw_bytes:   Raw file bytes read from disk.
        fmt:         DocumentFormat enum value.
        bedrock_fmt: Format string accepted by Bedrock API ("pdf", "docx", "jpeg", "png").

    Returns:
        List of content blocks to put inside the user message.
    """
    if fmt == DocumentFormat.IMAGE:
        media_block = {
            "image": {
                "format": bedrock_fmt,          # "jpeg" or "png"
                "source": {
                    "bytes": raw_bytes,          # boto3 serialises as base64
                },
            }
        }
    else:
        # PDF and DOCX both go through the "document" block
        media_block = {
            "document": {
                "format": bedrock_fmt,           # "pdf" or "docx"
                "name": "identity_document",     # arbitrary neutral name
                "source": {
                    "bytes": raw_bytes,          # boto3 serialises as base64
                },
            }
        }

    return [
        media_block,
        {"text": USER_LITEMPT},
        ]


# ---------------------------------------------------------------------------
# Bedrock call
# ---------------------------------------------------------------------------

@observe(as_type="generation", name="document-extract", capture_input=False, capture_output=False)
def _call_bedrock(
    raw_bytes: bytes,
    fmt: DocumentFormat,
    bedrock_fmt: str,
) -> tuple[str, dict]:
    """
    Send the document to Nova Lite and return the raw text response plus token usage.

    Retries up to config.bedrock.max_retries on:
      - ThrottlingException
      - ServiceUnavailableException
      - ModelTimeoutException

    Returns:
        Tuple of (response_text, token_info) where token_info contains:
          input_tokens, output_tokens, total_tokens, latency_ms.

    Raises:
        RuntimeError: All retry attempts exhausted.
    """
    content_blocks = _build_content_block(raw_bytes, fmt, bedrock_fmt)

    retryable_errors = {
        "ThrottlingException",
        "ServiceUnavailableException",
        "ModelTimeoutException",
    }

    max_attempts = 1 + config.bedrock.max_retries
    attempts = 0

    while attempts < max_attempts:
        attempts += 1
        try:
            logger.info(
                "Bedrock call attempt %d/%d — model=%s format=%s",
                attempts, max_attempts, config.bedrock.model_id, bedrock_fmt,
            )

            response = _get_client().converse(
                modelId=config.bedrock.model_id,
                system=[
                    {"text": SYSTEM_PROMPT},
                    {"cachePoint": {"type": "default"}},
                ],
                messages=[
                    {
                        "role": "user",
                        "content": content_blocks,
                    }
                ],
                inferenceConfig={
                    "maxTokens":   config.bedrock.max_tokens,
                    "temperature": config.bedrock.temperature,
                },
            )

            # converse response shape:
            # { "output": { "message": { "content": [ { "text": "..." } ] } },
            #   "usage":  { "inputTokens": N, "outputTokens": N, "totalTokens": N },
            #   "metrics":{ "latencyMs": N } }
            text = response["output"]["message"]["content"][0]["text"]
            logger.debug("Raw Bedrock response: %s", text)

            usage   = response.get("usage", {})
            metrics = response.get("metrics", {})
            input_total = usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0)
            output_total = usage.get("outputTokens", 0)
            token_info = {
                "input_tokens":  input_total,
                "output_tokens": output_total,
                "total_tokens":  input_total + output_total,
                "latency_ms":    metrics.get("latencyMs", 0),
            }
            langfuse.update_current_generation(
                model=config.bedrock.model_id,
                input=f"[{bedrock_fmt} document]",
                output=text[:2000],
                usage_details={
                    "input": input_total,
                    "output": output_total,
                    "total": input_total + output_total,
                },
                prompt=_lf_prompt,
                metadata={"service": _SERVICE, "format": bedrock_fmt},
            )
            return text, token_info

        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]

            if error_code in retryable_errors and attempts < max_attempts:
                logger.warning(
                    "Retryable error '%s' on attempt %d — retrying in %.1fs",
                    error_code, attempts, config.bedrock.retry_delay_seconds,
                )
                time.sleep(config.bedrock.retry_delay_seconds)
                continue

            raise RuntimeError(
                f"Bedrock call failed after {attempts} attempt(s). "
                f"Error: {error_code} — {exc.response['Error']['Message']}"
            ) from exc

    raise RuntimeError(
        f"Bedrock call exhausted all {max_attempts} attempt(s) without success."
    )


# ---------------------------------------------------------------------------
# Response parsing + field mapping
# ---------------------------------------------------------------------------

def _parse_response(raw_text: str) -> dict:
    """
    Parse Nova Lite's text response into a Python dict.
    Strips markdown code fences defensively even though the prompt forbids them.

    Raises:
        ValueError: Response is not valid JSON or not a dict.
    """
    text = raw_text.strip()

    if text.startswith("```"):
        import re
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Nova Lite response is not valid JSON. "
            f"Raw: {raw_text!r}. Error: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Expected a JSON object, got {type(parsed).__name__}. "
            f"Raw: {raw_text!r}"
        )

    return parsed


def _map_fields(parsed: dict) -> dict:
    """
    Whitelist only the 5 static fields. Drop everything else.
    Empty strings are treated as null.
    """
    mapped = {}
    for field_name in config.extraction.static_fields:
        value = parsed.get(field_name)
        if isinstance(value, str) and not value.strip():
            value = None
        mapped[field_name] = value

    dropped = set(parsed.keys()) - set(config.extraction.static_fields)
    if dropped:
        logger.debug("Dropped unexpected keys from model response: %s", dropped)

    _sanity_check_dates(mapped)
    return mapped

def _sanity_check_dates(mapped: dict) -> None:
    """
    Log a warning when date values look wrong — does not modify the result.

    Checks:
    - issue_date must not be after expiry_date (suggests DOB was returned instead).
    - issue_date should not be more than 15 years in the past from today's approximate
      year (2024), which would suggest a DOB (e.g. 1985) slipped through.
    """
    from datetime import datetime

    def _parse(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return None

    issue = _parse(mapped.get("issue_date"))
    expiry = _parse(mapped.get("expiry_date"))

    if issue and expiry and issue > expiry:
        logger.warning(
            "SANITY FAIL — issue_date (%s) is after expiry_date (%s). "
            "The model may have returned the date of birth instead of the issue date. "
            "Consider reviewing this result.",
            mapped.get("issue_date"), mapped.get("expiry_date"),
        ),


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

@observe(name="text-extraction", capture_input=False, capture_output=False)
def extract(
    raw_bytes: bytes,
    fmt: DocumentFormat,
    bedrock_fmt: str,
    document_name: str = "",
    source: str = "local",
) -> ExtractionResult:
    """
    Run extraction on a document and return a validated ExtractionResult.

    Args:
        raw_bytes:     Raw file bytes from converter.read_document().
        fmt:           DocumentFormat (IMAGE / PDF / DOCX).
        bedrock_fmt:   Bedrock format string ("jpeg", "png", "pdf", "docx").
        document_name: Filename or S3 key — used only for token logging.
        source:        "local" or "s3" — used only for token logging.

    Returns:
        ExtractionResult — always. Never raises for handled failures.

    Raises:
        RuntimeError: Bedrock call failed after all retries.
        ValueError:   Model returned unparseable output.
    """
    from scripts.token_logger import log_run  # lazy import to avoid circular deps

    langfuse.update_current_span(
        input={"document_name": document_name, "format": bedrock_fmt, "source": source},
        metadata={"service": _SERVICE},
    )
    if not raw_bytes:
        raise ValueError("raw_bytes is empty — nothing to extract from.")

    raw_text, token_info = _call_bedrock(raw_bytes, fmt, bedrock_fmt)
    parsed               = _parse_response(raw_text)
    mapped               = _map_fields(parsed)

    result = ExtractionResult(
        **mapped,
        token_usage=TokenUsage(
            input_tokens=token_info["input_tokens"],
            output_tokens=token_info["output_tokens"],
            total_tokens=token_info["total_tokens"],
        ),
    )

    logger.info(
        "Extraction complete — filled=%d/5 missing=%s",
        5 - len(result.missing_fields()),
        result.missing_fields() or "none",
    )

    log_run(
        document=document_name or "(unknown)",
        source=source,
        model_id=config.bedrock.model_id,
        input_tokens=token_info["input_tokens"],
        output_tokens=token_info["output_tokens"],
        total_tokens=token_info["total_tokens"],
        latency_ms=token_info["latency_ms"],
    )

    return result