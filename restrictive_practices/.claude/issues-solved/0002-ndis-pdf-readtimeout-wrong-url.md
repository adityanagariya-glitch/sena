---
id: "0002"
title: ReadTimeout downloading NDIS Regulated Restrictive Practices Guide
date: 2026-05-01
symptom_keywords: ReadTimeout timeout download ndis regulated restrictive practice guide 404 url
files_affected: scripts/ingest_ndis_policies.py
---

## Symptom
```
httpx.ReadTimeout — Attempt 1/3 failed (ReadTimeout) — retrying in 2s...
Attempt 2/3 failed (ReadTimeout) — retrying in 4s...
Attempt 3/3 failed (ReadTimeout) — retrying in 8s...
RuntimeError: Download failed after 3 attempts
```
Only the first document (Regulated Restrictive Practices Guide) failed. Other 4 documents succeeded.

## Root Cause
The URL path was wrong. The `_0` suffix variant (`regulated-restrictive-practice-guide-rrp-20200_0.pdf`)
returns a 404 or WAF timeout. The correct URL uses the 2022-02 date prefix with no `_0` suffix.

Wrong URL:
```
https://www.ndiscommission.gov.au/sites/default/files/2024-09/regulated-restrictive-practice-guide-rrp-20200_0.pdf
```

Correct URL:
```
https://www.ndiscommission.gov.au/sites/default/files/2022-02/regulated-restrictive-practice-guide-rrp-20200.pdf
```

## Fix
Updated `NDIS_DOCUMENTS[0]["url"]` in `scripts/ingest_ndis_policies.py` to the 2022-02 path.
Also added retry with exponential backoff (3 attempts, 2/4/8 second waits).

## Verification
`python scripts/ingest_ndis_policies.py` — first document downloads without timeout.

## Watch Out For
- Government sites restructure PDF URLs when updating documents — if this fails again,
  manually browse ndiscommission.gov.au to find the current URL
- The local pdfs/ folder fallback handles this gracefully — manual download is always an option
