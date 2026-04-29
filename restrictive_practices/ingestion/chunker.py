"""PDF text extraction and semantic chunking for NDIS policy documents."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    category: str
    document_source: str
    risk_level: str


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    return "\n\n".join(pages)


def chunk_document(
    text: str,
    document_source: str,
    category: str,
    risk_level: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[DocumentChunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        # Prefer splitting on paragraph → sentence → word boundaries
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    texts = splitter.split_text(text)
    chunks = []
    for i, raw in enumerate(texts):
        text_clean = raw.strip()
        if not text_clean:
            continue
        # Deterministic ID so re-ingesting the same doc is idempotent
        chunk_id = hashlib.sha256(f"{document_source}::{i}".encode()).hexdigest()[:24]
        chunks.append(DocumentChunk(
            chunk_id=chunk_id,
            text=text_clean,
            category=category,
            document_source=document_source,
            risk_level=risk_level,
        ))
    return chunks


def chunk_text(
    text: str,
    document_source: str,
    category: str,
    risk_level: str,
) -> list[DocumentChunk]:
    """Convenience wrapper for plain text (no PDF extraction needed)."""
    return chunk_document(text, document_source, category, risk_level)
