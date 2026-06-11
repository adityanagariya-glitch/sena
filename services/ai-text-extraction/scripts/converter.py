"""
converter.py
------------
Responsible only for:
  1. Detecting the format of an uploaded document.
  2. Reading the raw bytes from disk.

Nova Lite on Bedrock natively accepts PDF, DOCX, and images (JPG/PNG).
No conversion is required — the model handles the format directly.
"""

import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supported document formats
# ---------------------------------------------------------------------------

class DocumentFormat(str, Enum):
    IMAGE = "image"   # JPG, PNG
    PDF   = "pdf"
    DOCX  = "docx"


# Mapping: file extension → (DocumentFormat, bedrock_format_string)
# bedrock_format_string is the value passed to the Bedrock API "format" field
_EXT_MAP: dict[str, tuple[DocumentFormat, str]] = {
    ".jpg":  (DocumentFormat.IMAGE, "jpeg"),
    ".jpeg": (DocumentFormat.IMAGE, "jpeg"),
    ".png":  (DocumentFormat.IMAGE, "png"),
    ".webp": (DocumentFormat.IMAGE, "webp"),
    ".pdf":  (DocumentFormat.PDF,   "pdf"),
    ".docx": (DocumentFormat.DOCX,  "docx"),
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def detect_format(file_path: str | Path) -> tuple[DocumentFormat, str]:
    """
    Detect document format from file extension.

    Args:
        file_path: Path to the uploaded file.

    Returns:
        Tuple of (DocumentFormat, bedrock_format_string).
        e.g. (DocumentFormat.PDF, "pdf")

    Raises:
        ValueError: If the extension is not supported.
    """
    ext = Path(file_path).suffix.lower()
    if ext not in _EXT_MAP:
        raise ValueError(
            f"Unsupported file extension '{ext}'. "
            f"Supported: {list(_EXT_MAP.keys())}"
        )
    return _EXT_MAP[ext]


def read_document(file_path: str | Path) -> tuple[bytes, DocumentFormat, str]:
    """
    Read a document from disk and return its raw bytes + format info.

    No conversion is performed. Nova Lite accepts PDF, DOCX, and images
    natively via the Bedrock document/image block API.

    Args:
        file_path: Path to the uploaded file.

    Returns:
        Tuple of (raw_bytes, DocumentFormat, bedrock_format_string).

    Raises:
        FileNotFoundError: File does not exist.
        ValueError:        Unsupported file extension.
        RuntimeError:      File is empty.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    fmt, bedrock_fmt = detect_format(file_path)

    raw_bytes = file_path.read_bytes()
    if not raw_bytes:
        raise RuntimeError(f"File is empty: {file_path.name}")

    logger.info(
        "Document read — file=%s format=%s size=%d bytes",
        file_path.name, fmt.value, len(raw_bytes),
    )
    return raw_bytes, fmt, bedrock_fmt