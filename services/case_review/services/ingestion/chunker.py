"""PDF text extraction, semantic chunking, and parent-child hierarchy for NDIS policy docs.

Architecture
------------
Parent chunks  — full semantic sections (one per numbered heading / regulation block).
                 ~800-1500 chars. Sent to the evaluator for full context.
Child chunks   — small sub-sections (~300 chars) from splitting each parent.
                 Embedded for high-precision retrieval (embedding focuses on one idea).

At query time:
  1. Retrieve matching CHILD chunks (vector + BM25)
  2. Fetch their PARENT chunks
  3. Send parent text to evaluator (full regulatory context, not a cut-off sentence)

Chunking strategy
-----------------
1. Regex-based section detection: NDIS PDFs use numbered sections (1., 1.1, etc.)
   and ALL-CAPS headers. Detected boundaries become parent chunk boundaries.
2. Fallback: if <3 sections found, use fixed 1200-char parents (same as legacy).
3. LLM-assisted: pass --llm-assist to ingest script → Haiku identifies boundaries.
   One-time cost per document during ingest.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langfuse import observe, get_client

from core.settings import settings

langfuse = get_client()
_SERVICE = "case_review_ingest_chunker"

# Regex patterns for NDIS policy PDF section headers
_SECTION_PATTERN = re.compile(
    r"(?m)^("
    r"\d+\.\d+(?:\.\d+)?\s+[A-Z]"   # 1.1 Title or 1.1.1 Title
    r"|(?<!\d)\d+\.\s+[A-Z]"         # 1. Title (not mid-sentence)
    r"|Section\s+\d+"                 # Section 1
    r"|CHAPTER\s+\d+"                 # CHAPTER 1
    r"|Part\s+[A-Z0-9]+"             # Part A / Part 1
    r"|[A-Z][A-Z\s]{8,}(?=\n)"       # ALL CAPS HEADER (min 9 chars)
    r")"
)


@dataclass
class DocumentChunk:
    """Flat chunk — used for legacy ingest and as the return type for both parent and child."""
    chunk_id: str
    text: str
    category: str
    document_source: str
    risk_level: str
    document_type: str = field(default="Regulatory")
    parent_chunk_id: str | None = field(default=None)
    is_parent: bool = field(default=False)


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    return "\n\n".join(pages)


# ── Semantic section detection ────────────────────────────────────────────────

def _split_into_sections(text: str) -> list[str]:
    """Split text at NDIS-policy section headers using regex.

    Returns a list of section strings. If fewer than 3 sections found,
    returns the full text as a single section (fallback to fixed-size chunking).
    """
    boundaries = [m.start() for m in _SECTION_PATTERN.finditer(text)]

    if len(boundaries) < 3:
        # Not enough structure detected — treat as one section, fixed-size parent below
        return [text]

    sections = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)
    return sections


async def detect_sections_with_llm(text: str, *, api_key: str, model_id: str) -> list[str]:
    """LLM-assisted section detection using Haiku (one-time ingest only).

    Feed the full document text to Haiku and ask it to identify where each
    major regulatory section starts. More accurate than regex for PDFs with
    non-standard formatting (e.g., scanned, reformatted, or merged documents).

    Returns a list of section strings, same format as _split_into_sections().
    """
    import asyncio
    import json
    import boto3

    # Sample: LLM reads first 12000 chars to detect the pattern, then we apply globally
    sample = text[:12000]

    @observe(as_type="generation", name="case-review-ingest-section-detect", capture_input=False, capture_output=False)
    def _call_llm() -> list[int]:
        kwargs: dict[str, Any] = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        client = boto3.client("bedrock-runtime", **kwargs)

        prompt = (
            "You are processing an NDIS (National Disability Insurance Scheme) policy PDF.\n\n"
            "Find every section heading in the text below. Return a JSON array of the EXACT "
            "first few words of each heading (enough to identify it uniquely).\n\n"
            "Rules:\n"
            "- Include numbered sections (1., 1.1, etc.), bold headers, and chapter titles\n"
            "- Return ONLY a JSON array of strings, no other text\n"
            "- Example: [\"1. Introduction\", \"1.1 Scope\", \"2. Definitions\"]\n\n"
            f"Document text (first portion):\n---\n{sample}\n---"
        )
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
        )
        raw = response["output"]["message"]["content"][0]["text"]
        usage = response.get("usage", {})
        langfuse.update_current_generation(
            model=model_id,
            input=sample[:2000],
            output=raw[:2000],
            usage_details={
                "input": usage.get("inputTokens", 0),
                "output": usage.get("outputTokens", 0),
            },
            metadata={"service": _SERVICE},
        )
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        return json.loads(raw[start:end])

    try:
        headings = await asyncio.to_thread(_call_llm)
    except Exception:
        # Fallback to regex if LLM call fails
        return _split_into_sections(text)

    if not headings or len(headings) < 3:
        return _split_into_sections(text)

    # Build a regex from the detected headings to find their positions in full text
    escaped = [re.escape(h[:40]) for h in headings]
    pattern = re.compile(r"(?m)^(" + "|".join(escaped) + r")")
    boundaries = [m.start() for m in pattern.finditer(text)]

    if len(boundaries) < 3:
        return _split_into_sections(text)

    sections = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)
    return sections


# ── Parent-child chunking ─────────────────────────────────────────────────────

def _make_chunk_id(source: str, suffix: str) -> str:
    return hashlib.sha256(f"{source}::{suffix}".encode()).hexdigest()[:24]


def semantic_chunk_document(
    text: str,
    document_source: str,
    category: str,
    risk_level: str,
    document_type: str = "Regulatory",
    sections: list[str] | None = None,
) -> list[DocumentChunk]:
    """Create parent + child chunks from document text.

    Parents: one per semantic section (full regulatory rule, 800-1500 chars).
             is_parent=True, no embedding, parent_chunk_id=None.
    Children: 300-char splits of each parent.
             is_parent=False, embedded for retrieval, parent_chunk_id set.

    If a section is very short (<200 chars), it's stored as parent-only
    (no children — it's already small enough to retrieve directly as a flat chunk).

    Args:
        sections: pre-computed sections (from LLM or regex). If None, auto-detected.
    """
    all_sections = sections if sections is not None else _split_into_sections(text)

    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    # Fallback: if only 1 section (no structure detected), use fixed-size parents
    if len(all_sections) == 1:
        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        all_sections = [s for s in parent_splitter.split_text(text) if s.strip()]

    chunks: list[DocumentChunk] = []

    for p_idx, section_text in enumerate(all_sections):
        section_text = section_text.strip()
        if not section_text:
            continue

        parent_id = _make_chunk_id(document_source, f"p{p_idx}")

        if len(section_text) < 200:
            # Section is already small — store as flat retrievable chunk (no parent overhead)
            chunks.append(DocumentChunk(
                chunk_id=parent_id,
                text=section_text,
                category=category,
                document_source=document_source,
                risk_level=risk_level,
                document_type=document_type,
                parent_chunk_id=None,
                is_parent=False,
            ))
            continue

        # Store parent (full section — sent to evaluator for context)
        chunks.append(DocumentChunk(
            chunk_id=parent_id,
            text=section_text,
            category=category,
            document_source=document_source,
            risk_level=risk_level,
            document_type=document_type,
            parent_chunk_id=None,
            is_parent=True,
        ))

        # Store children (small splits — embedded for retrieval precision)
        child_texts = child_splitter.split_text(section_text)
        for c_idx, child_text in enumerate(child_texts):
            child_text = child_text.strip()
            if not child_text:
                continue
            child_id = _make_chunk_id(document_source, f"p{p_idx}c{c_idx}")
            chunks.append(DocumentChunk(
                chunk_id=child_id,
                text=child_text,
                category=category,
                document_source=document_source,
                risk_level=risk_level,
                document_type=document_type,
                parent_chunk_id=parent_id,
                is_parent=False,
            ))

    return chunks


# ── Legacy flat chunking (kept for compatibility) ─────────────────────────────

def chunk_document(
    text: str,
    document_source: str,
    category: str,
    risk_level: str,
    document_type: str = "Regulatory",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[DocumentChunk]:
    """Legacy fixed-size chunking. Use semantic_chunk_document() for new ingests."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=chunk_overlap or settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = []
    for i, raw in enumerate(splitter.split_text(text)):
        text_clean = raw.strip()
        if not text_clean:
            continue
        chunk_id = _make_chunk_id(document_source, str(i))
        chunks.append(DocumentChunk(
            chunk_id=chunk_id,
            text=text_clean,
            category=category,
            document_source=document_source,
            risk_level=risk_level,
            document_type=document_type,
        ))
    return chunks


def chunk_text(
    text: str,
    document_source: str,
    category: str,
    risk_level: str,
    document_type: str = "Regulatory",
) -> list[DocumentChunk]:
    """Convenience wrapper for plain text (no PDF extraction needed)."""
    return chunk_document(text, document_source, category, risk_level, document_type)
