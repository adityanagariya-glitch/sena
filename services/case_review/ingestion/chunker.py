"""PDF text extraction and semantic chunking for NDIS policy documents."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    category: str
    document_source: str
    risk_level: str
    document_type: str = field(default="Regulatory")


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    return "\n\n".join(pages)


def chunk_document(
    text: str,
    document_source: str,
    category: str,
    risk_level: str,
    document_type: str = "Regulatory",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[DocumentChunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.chunk_size,
        chunk_overlap=chunk_overlap or settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    texts = splitter.split_text(text)
    chunks = []
    for i, raw in enumerate(texts):
        text_clean = raw.strip()
        if not text_clean:
            continue
        chunk_id = hashlib.sha256(f"{document_source}::{i}".encode()).hexdigest()[:24]
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
