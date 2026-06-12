"""
s3_client.py
------------
Downloads a document from S3 by object key.
Returns raw bytes and the filename (last segment of the key).

Usage:
    from scripts.s3_client import download
    raw_bytes, filename = download("uploads/abc123/passport.pdf")
"""

import logging

import boto3
from botocore.exceptions import ClientError

from scripts.config import config

logger = logging.getLogger(__name__)


def download(s3_key: str) -> tuple[bytes, str]:
    """
    Download a document from the configured S3 bucket.

    Args:
        s3_key: S3 object key, e.g. "uploads/2024/passport.pdf"

    Returns:
        Tuple of (raw_bytes, filename).
        filename is the last path segment of the key (e.g. "passport.pdf").

    Raises:
        ValueError:      S3_BUCKET_NAME env var is not set.
        FileNotFoundError: Object does not exist in the bucket.
        RuntimeError:    Any other S3 error.
    """
    bucket = config.s3.bucket_name
    if not bucket:
        raise ValueError(
            "S3_BUCKET_NAME environment variable is not set. "
            "Set it before using the S3 extraction endpoint."
        )

    filename = s3_key.split("/")[-1]

    logger.info("S3 download — bucket=%s key=%s", bucket, s3_key)

    client = boto3.client("s3", region_name=config.s3.region)

    try:
        response = client.get_object(Bucket=bucket, Key=s3_key)
        raw_bytes = response["Body"].read()
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("NoSuchKey", "404"):
            raise FileNotFoundError(
                f"S3 object not found — bucket={bucket} key={s3_key}"
            ) from exc
        raise RuntimeError(
            f"S3 download failed — {error_code}: {exc.response['Error']['Message']}"
        ) from exc

    if not raw_bytes:
        raise RuntimeError(f"S3 object is empty — key={s3_key}")

    logger.info(
        "S3 download complete — file=%s size=%d bytes", filename, len(raw_bytes)
    )
    return raw_bytes, filename
