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
import time

import boto3
import httpx

from case_review.core.settings import settings

logger = logging.getLogger(__name__)

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


def _make_s3_client() -> "boto3.client":
    # Use S3-specific credentials when provided; fall back to Bedrock creds.
    region = settings.s3_region or settings.aws_region
    kwargs: dict = {"region_name": region}
    key_id = settings.s3_access_key_id or settings.aws_access_key_id
    secret = settings.s3_secret_access_key or settings.aws_secret_access_key
    if key_id:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("s3", **kwargs)


def _make_transcribe_client() -> "boto3.client":
    # Transcribe must be in the same account as the S3 bucket it reads from.
    region = settings.s3_region or settings.aws_region
    kwargs: dict = {"region_name": region}
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


async def _fetch_transcript(uri: str) -> str:
    """Fetch the Transcribe JSON result and extract the transcript text."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(uri)
        resp.raise_for_status()
    data = resp.json()
    # Transcribe result shape: {"results": {"transcripts": [{"transcript": "..."}], ...}}
    transcripts = data.get("results", {}).get("transcripts", [])
    if not transcripts:
        raise RuntimeError("Transcribe result contained no transcript text")
    return transcripts[0]["transcript"]


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
        logger.info("transcription: extracted %d chars from job %s", len(transcript), job_name)
        return transcript
    finally:
        await asyncio.to_thread(_delete_s3_key, bucket, s3_key)
