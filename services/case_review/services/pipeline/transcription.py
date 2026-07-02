"""Speech-to-text via Amazon Transcribe (batch mode).

Used by POST /draft/audio to convert a support worker's audio recording into
a text transcript before passing it to the existing run_drafter() pipeline.

Flow:
  1. Upload audio bytes to S3 temp key
  2. Start a Transcribe batch job (en-AU, optional custom vocabulary)
  3. Poll until COMPLETED (2s interval, 120s max)
  4. Fetch transcript JSON from the result URL
  5. Delete S3 temp key (always, in finally)
  6. Return the transcript string

All boto3 calls are synchronous and offloaded via asyncio.to_thread.
"""

import asyncio
import json
import logging
import re
import time

import boto3
import httpx
from botocore.config import Config

from core.settings import settings

logger = logging.getLogger(__name__)

# Vocalized hesitation sounds only — "um / uh / er / erm / err" and their
# elongations. Never lexical content in English, so removing them cannot change
# clinical meaning. Deliberately NOT stripping "ah / oh / hmm / mm / like /
# you know / well / so" — in a support-work record those can carry meaning.
# NOTE: kept byte-identical with voice/services/transcribe_service.py's
# strip_fillers; the two services are intentionally isolated (no shared import
# path), so this small pure helper is duplicated rather than shared.
_FILLER_RE = re.compile(r"\b(?:um+|uh+|erm+|err+|er+)\b", re.IGNORECASE)


def _strip_fillers(text: str) -> str:
    """Remove vocalized filler sounds from an ASR transcript (meaning-preserving)."""
    cleaned = _FILLER_RE.sub("", text)
    cleaned = re.sub(r",(?:\s*,)+", ",", cleaned)       # collapse commas orphaned by removal
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)  # drop space before punctuation
    cleaned = re.sub(r",\s*([.!?])", r"\1", cleaned)    # drop comma stranded before sentence end
    cleaned = re.sub(r"\s{2,}", " ", cleaned)           # collapse runs of whitespace
    cleaned = re.sub(r"^[\s,]+", "", cleaned)           # trim leading space/comma
    return cleaned.strip()

# Supported MIME type → Transcribe media format
_MIME_TO_FORMAT: dict[str, str] = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "video/mp4": "mp4",
    "audio/x-m4a": "mp4",
    "audio/m4a": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "video/webm": "webm",
}

# Extension fallback when MIME type is generic/octet-stream
_EXT_TO_FORMAT: dict[str, str] = {
    "mp3": "mp3",
    "mp4": "mp4",
    "m4a": "mp4",
    "wav": "wav",
    "flac": "flac",
    "ogg": "ogg",
    "webm": "webm",
}

_POLL_INTERVAL_SEC = 2
_POLL_TIMEOUT_SEC = 120

_S3_CONFIG = Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 2, "mode": "standard"})
_TRANSCRIBE_CONFIG = Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2, "mode": "standard"})


def _make_s3_client() -> "boto3.client":
    # Use S3-specific credentials when provided; fall back to Bedrock creds.
    region = settings.s3_region or settings.aws_region
    kwargs: dict = {"region_name": region, "config": _S3_CONFIG}
    key_id = settings.s3_access_key_id or settings.aws_access_key_id
    secret = settings.s3_secret_access_key or settings.aws_secret_access_key
    if key_id:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("s3", **kwargs)


def _make_transcribe_client() -> "boto3.client":
    # Transcribe must be in the same account as the S3 bucket it reads from.
    region = settings.s3_region or settings.aws_region
    kwargs: dict = {"region_name": region, "config": _TRANSCRIBE_CONFIG}
    key_id = settings.s3_access_key_id or settings.aws_access_key_id
    secret = settings.s3_secret_access_key or settings.aws_secret_access_key
    if key_id:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("transcribe", **kwargs)


def resolve_media_format(content_type: str, filename: str) -> str:
    """Return Transcribe media format string or raise ValueError for unsupported types."""
    fmt = _MIME_TO_FORMAT.get(content_type.lower().split(";")[0].strip())
    if fmt:
        return fmt
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    fmt = _EXT_TO_FORMAT.get(ext)
    if fmt:
        return fmt
    raise ValueError(
        f"Unsupported audio format: content_type={content_type!r}, filename={filename!r}. "
        f"Supported: {sorted(set(_EXT_TO_FORMAT.values()))}"
    )


def _upload_audio(bucket: str, key: str, audio_bytes: bytes, content_type: str) -> None:
    s3 = _make_s3_client()
    s3.put_object(Bucket=bucket, Key=key, Body=audio_bytes, ContentType=content_type)
    logger.info("transcription: uploaded s3://%s/%s (%d bytes)", bucket, key, len(audio_bytes))


def _start_job(job_name: str, s3_uri: str, media_format: str) -> None:
    tc = _make_transcribe_client()
    kwargs: dict = {
        "TranscriptionJobName": job_name,
        "Media": {"MediaFileUri": s3_uri},
        "MediaFormat": media_format,
        "LanguageCode": settings.transcription_language,
        "Settings": {"ShowSpeakerLabels": False},
    }
    if settings.transcription_vocab_name:
        kwargs["Settings"]["VocabularyName"] = settings.transcription_vocab_name
    tc.start_transcription_job(**kwargs)
    logger.info("transcription: started job %s format=%s lang=%s", job_name, media_format, settings.transcription_language)


def _poll_job(job_name: str) -> str:
    """Block until job completes; return TranscriptFileUri."""
    tc = _make_transcribe_client()
    deadline = time.monotonic() + _POLL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        resp = tc.get_transcription_job(TranscriptionJobName=job_name)
        status = resp["TranscriptionJob"]["TranscriptionJobStatus"]
        if status == "COMPLETED":
            uri = resp["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
            logger.info("transcription: job %s COMPLETED", job_name)
            return uri
        if status == "FAILED":
            reason = resp["TranscriptionJob"].get("FailureReason", "unknown")
            raise RuntimeError(f"Transcribe job {job_name} FAILED: {reason}")
        time.sleep(_POLL_INTERVAL_SEC)
    raise TimeoutError(f"Transcribe job {job_name} did not complete within {_POLL_TIMEOUT_SEC}s")


def _delete_s3_key(bucket: str, key: str) -> None:
    try:
        s3 = _make_s3_client()
        s3.delete_object(Bucket=bucket, Key=key)
        logger.info("transcription: deleted s3://%s/%s", bucket, key)
    except Exception as exc:
        logger.warning("transcription: failed to delete s3://%s/%s: %s", bucket, key, exc)


async def _fetch_transcript(uri: str, max_retries: int = 3) -> str:
    """Fetch the Transcribe JSON result and extract the transcript text.

    Retries on signature errors (credential expiration or clock skew).
    """
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(uri)
                if resp.status_code == 403 and "SignatureDoesNotMatch" in resp.text:
                    if attempt < max_retries - 1:
                        wait_sec = 2 ** attempt  # exponential backoff: 1, 2, 4 seconds
                        logger.warning("transcription: S3 signature error, retrying in %ds (attempt %d/%d)", wait_sec, attempt + 1, max_retries)
                        await asyncio.sleep(wait_sec)
                        continue
                    raise RuntimeError(f"S3 signature validation failed after {max_retries} attempts — check clock sync and credentials")
                resp.raise_for_status()
            data = resp.json()
            # Transcribe result shape: {"results": {"transcripts": [{"transcript": "..."}], ...}}
            transcripts = data.get("results", {}).get("transcripts", [])
            if not transcripts:
                raise RuntimeError("Transcribe result contained no transcript text")
            return transcripts[0]["transcript"]
        except httpx.HTTPError as exc:
            if attempt < max_retries - 1:
                wait_sec = 2 ** attempt
                logger.warning("transcription: fetch failed (%s), retrying in %ds (attempt %d/%d)", exc, wait_sec, attempt + 1, max_retries)
                await asyncio.sleep(wait_sec)
                continue
            raise RuntimeError(f"Failed to fetch transcript after {max_retries} attempts: {exc}") from exc


async def run_transcription(
    audio_bytes: bytes,
    media_format: str,
    *,
    job_name: str,
) -> str:
    """Upload audio to S3, run Transcribe batch job, return transcript string.

    Deletes the S3 temp key regardless of success or failure.
    Raises RuntimeError / TimeoutError on job failure or timeout.
    """
    bucket = settings.s3_bucket or settings.transcription_bucket
    s3_key = f"transcribe-temp/{job_name}.{media_format}"
    s3_uri = f"s3://{bucket}/{s3_key}"

    try:
        await asyncio.to_thread(_upload_audio, bucket, s3_key, audio_bytes, f"audio/{media_format}")
        await asyncio.to_thread(_start_job, job_name, s3_uri, media_format)
        transcript_uri = await asyncio.to_thread(_poll_job, job_name)
        transcript = await _fetch_transcript(transcript_uri)
        raw_len = len(transcript)
        transcript = _strip_fillers(transcript)
        logger.info(
            "transcription: extracted %d chars from job %s (%d after filler strip)",
            raw_len, job_name, len(transcript),
        )
        return transcript
    finally:
        await asyncio.to_thread(_delete_s3_key, bucket, s3_key)
