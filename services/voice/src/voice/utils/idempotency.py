from __future__ import annotations


def build_idempotency_key(entity_id: str, version: int) -> str:
    return f"{entity_id}:{version}"
