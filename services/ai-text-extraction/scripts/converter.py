"""
converter.py
------------
Responsible only for:
  1. Detecting the format of an uploaded document.
  2. Reading the raw bytes from disk, converting non-native formats to JPEG.

Nova Lite on Bedrock natively accepts PDF, DOCX, JPEG, PNG, and WebP.
HEIF/HEIC (iPhone/Samsung) and AVIF (Google Pixel/Android) are converted
to JPEG in memory before being sent to Bedrock.
"""

import io
import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions that need Pillow conversion → JPEG before sending to Bedrock
_PILLOW_CONVERT_EXTS = frozenset({
    ".heif", ".heic",   # iPhone / Samsung
    ".avif",            # Google Pixel / modern Android
})


# ---------------------------------------------------------------------------
# Supported document formats
# ---------------------------------------------------------------------------

class DocumentFormat(str, Enum):
    IMAGE = "image"
    PDF   = "pdf"
    DOCX  = "docx"


# Mapping: file extension → (DocumentFormat, bedrock_format_string)
_EXT_MAP: dict[str, tuple[DocumentFormat, str]] = {
    # Native Bedrock image formats
    ".jpg":  (DocumentFormat.IMAGE, "jpeg"),
    ".jpeg": (DocumentFormat.IMAGE, "jpeg"),
    ".png":  (DocumentFormat.IMAGE, "png"),
    ".webp": (DocumentFormat.IMAGE, "webp"),
    # Converted to JPEG before Bedrock
    ".heif": (DocumentFormat.IMAGE, "jpeg"),# iPhone / Samsung (Apple HEIF container)
    ".heic": (DocumentFormat.IMAGE, "jpeg"),# iPhone / Samsung (Apple HEIF container)
    ".avif": (DocumentFormat.IMAGE, "jpeg"),# Google Pixel / modern Android (AV1 Image Format)
    # Document formats
    ".pdf":  (DocumentFormat.PDF,   "pdf"),
    ".docx": (DocumentFormat.DOCX,  "docx"),
}


def _to_jpeg(file_path: Path) -> bytes:
    """Convert HEIF/HEIC/AVIF to JPEG bytes using Pillow."""
    ext = file_path.suffix.lower()

    if ext in {".heif", ".heic"}:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError as exc:
            raise RuntimeError(
                "pillow-heif is required for HEIF/HEIC files: pip install pillow-heif"
            ) from exc

    if ext == ".avif":
        try:
            import pillow_avif  # noqa: F401 — registers the AVIF opener
        except ImportError:
            pass  # newer Pillow has built-in AVIF support; try anyway

    from PIL import Image
    with Image.open(file_path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def detect_format(file_path: str | Path) -> tuple[DocumentFormat, str]:
    """
    Detect document format from file extension.

    Returns:
        Tuple of (DocumentFormat, bedrock_format_string).

    Raises:
        ValueError: If the extension is not supported.
    """
    ext = Path(file_path).suffix.lower()
    if ext not in _EXT_MAP:
        raise ValueError(
            f"Unsupported file extension '{ext}'. "
            f"Supported: {sorted(_EXT_MAP.keys())}"
        )
    return _EXT_MAP[ext]


def read_document(file_path: str | Path) -> tuple[bytes, DocumentFormat, str]:
    """
    Read a document from disk and return its raw bytes + format info.

    HEIF, HEIC, and AVIF are converted to JPEG in memory.
    PDF, DOCX, JPEG, PNG, and WebP are returned as-is.

    Returns:
        Tuple of (raw_bytes, DocumentFormat, bedrock_format_string).

    Raises:
        FileNotFoundError: File does not exist.
        ValueError:        Unsupported file extension.
        RuntimeError:      File is empty or conversion failed.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    fmt, bedrock_fmt = detect_format(file_path)
    ext = file_path.suffix.lower()

    if ext in _PILLOW_CONVERT_EXTS:
        raw_bytes = _to_jpeg(file_path)
        logger.info(
            "Image converted to JPEG — file=%s original_ext=%s jpeg_size=%d bytes",
            file_path.name, ext, len(raw_bytes),
        )
    else:
        raw_bytes = file_path.read_bytes()
        if not raw_bytes:
            raise RuntimeError(f"File is empty: {file_path.name}")

    logger.info(
        "Document read — file=%s format=%s size=%d bytes",
        file_path.name, fmt.value, len(raw_bytes),
    )
    return raw_bytes, fmt, bedrock_fmt
