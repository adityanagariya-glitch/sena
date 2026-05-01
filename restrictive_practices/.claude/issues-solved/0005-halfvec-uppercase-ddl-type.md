---
id: "0005"
title: HALFVEC vs HalfVector — wrong type in mapped_column causes DDL error
date: 2026-05-01
symptom_keywords: HALFVEC HalfVector mapped_column DDL error pgvector column type
files_affected: models/db.py
---

## Symptom
```
sqlalchemy.exc.CompileError: Could not locate type 'HalfVector'
# or silently creates wrong column type in PostgreSQL
```

## Root Cause
Two different things share similar names in the pgvector + SQLAlchemy stack:
- `HALFVEC(3072)` — the DDL/column type string used in `mapped_column()` type annotation
- `HalfVector` — the Python runtime value class used when reading/writing vector values

Using `HalfVector(3072)` (runtime class) as the mapped_column type causes DDL errors.

## Fix
```python
# CORRECT — use uppercase string type for the column definition
from pgvector.sqlalchemy import HALFVEC

class NDISPolicyChunk(Base):
    embedding: Mapped[list[float]] = mapped_column(HALFVEC(3072), nullable=False)
```

```python
# WRONG — do not use HalfVector here
from pgvector.sqlalchemy import HalfVector
embedding: Mapped[list[float]] = mapped_column(HalfVector(3072))  # ← breaks DDL
```

## Verification
`create_tables()` completes without error; `\d rp_ndis_policy_chunks` in psql shows `halfvec(3072)` column type.

## Watch Out For
- HNSW index operator class must also match: `halfvec_cosine_ops` (not `vector_cosine_ops`)
- If switching to full float32 vectors, use `VECTOR(1536)` and `vector_cosine_ops`
