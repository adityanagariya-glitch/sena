---
id: "0001"
title: SSL error downloading PDFs from ndiscommission.gov.au
date: 2026-05-01
symptom_keywords: ssl certificate verify failed httpx ndis download government pdf
files_affected: scripts/ingest_ndis_policies.py, scripts/ingest_docs.py
---

## Symptom
```
ERROR: SSL: CERTIFICATE_VERIFY_FAILED
httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
```
Appeared as blank `ERROR:` line in terminal output.

## Root Cause
Windows trust store does not include the intermediate CA used by ndiscommission.gov.au.
Also, the government WAF blocks requests without a browser-like User-Agent.

## Fix
In all `httpx.AsyncClient` calls for government PDF downloads:
```python
async with httpx.AsyncClient(
    verify=False,           # skip CA check — acceptable for known public PDFs
    follow_redirects=True,
    timeout=httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0),
) as client:
    resp = await client.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/pdf,*/*",
    })
```

## Verification
`python scripts/ingest_ndis_policies.py` — no SSL error; downloads proceed.

## Watch Out For
- `verify=False` suppresses urllib3 InsecureRequestWarning — acceptable here (public docs)
- Do NOT disable verify for auth or API endpoints — only PDF downloads from known government URLs
