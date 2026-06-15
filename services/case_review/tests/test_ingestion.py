"""Tests for case_review.services.ingestion.chunker (pure, no I/O)."""
from __future__ import annotations

import pytest

from case_review.services.ingestion.chunker import DocumentChunk, chunk_document, chunk_text


def test_chunk_document_splits_long_text() -> None:
    text = " ".join(["word"] * 300)
    chunks = chunk_document(
        text,
        document_source="test.pdf",
        category="Restraint",
        risk_level="high",
        chunk_size=100,
        chunk_overlap=10,
    )
    assert len(chunks) > 1
    for c in chunks:
        assert isinstance(c, DocumentChunk)
        assert c.category == "Restraint"
        assert c.document_source == "test.pdf"
        assert c.risk_level == "high"
        assert c.document_type == "Regulatory"
        assert len(c.chunk_id) == 24


def test_chunk_document_ids_are_deterministic() -> None:
    text = "A " * 100
    c1 = chunk_document(text, "src", "Cat", "low", chunk_size=50, chunk_overlap=5)
    c2 = chunk_document(text, "src", "Cat", "low", chunk_size=50, chunk_overlap=5)
    assert [c.chunk_id for c in c1] == [c.chunk_id for c in c2]


def test_chunk_document_skips_empty_chunks() -> None:
    text = "\n\n\n".join(["Hello world"] * 5)
    chunks = chunk_document(text, "src", "Cat", "low")
    assert all(c.text.strip() for c in chunks)


def test_chunk_text_wrapper_matches_chunk_document() -> None:
    text = "Some policy text about restrictive practices. " * 20
    a = chunk_text(text, "src", "RP", "medium")
    b = chunk_document(text, "src", "RP", "medium")
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]


def test_document_chunk_default_document_type() -> None:
    chunks = chunk_document("word " * 50, "src", "cat", "low")
    assert all(c.document_type == "Regulatory" for c in chunks)


def test_document_chunk_custom_document_type() -> None:
    chunks = chunk_document(
        "word " * 50, "src", "cat", "low", document_type="BehaviourSupport"
    )
    assert all(c.document_type == "BehaviourSupport" for c in chunks)


def test_chunk_document_returns_empty_list_for_whitespace_only() -> None:
    chunks = chunk_document("   \n\n   ", "src", "cat", "low")
    assert chunks == []
