---
id: "0003"
title: Manual PDF not found in local fallback — filename mismatch
date: 2026-05-01
symptom_keywords: local file not found pdf fallback manual download filename mismatch browser save
files_affected: scripts/ingest_ndis_policies.py
---

## Symptom
After manually downloading PDFs to `pdfs/` folder, one document still tries to re-download
and fails, even though the file is clearly in the folder.

User saved: `regulated-restrictive-practice-guide-rrp-20200.pdf` (browser's default name)
Script looked for: `regulated-restrictive-practice-guide.pdf` (our `local_filename` value)

## Root Cause
`ingest_document()` only checked `_LOCAL_PDF_DIR / doc["local_filename"]`. Browsers save files
using the last path segment of the URL, not our chosen `local_filename`.

## Fix
Check both the canonical name AND the URL basename:
```python
url_basename = doc["url"].split("/")[-1]
local_candidates = [
    _LOCAL_PDF_DIR / doc["local_filename"],
    _LOCAL_PDF_DIR / url_basename,          # ← added: browser's default save name
]
local_path = next((p for p in local_candidates if p.exists()), None)
```

## Verification
Place file in `pdfs/` with either name — script picks it up without re-downloading.

## Watch Out For
- When adding new documents to `NDIS_DOCUMENTS`, always include both the canonical
  `local_filename` and the URL basename in mind — they often differ for government sites
