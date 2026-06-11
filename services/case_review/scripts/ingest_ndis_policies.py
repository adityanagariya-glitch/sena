"""One-shot ingestion of official NDIS policy PDFs from ndiscommission.gov.au.

Downloads 5 documents covering all regulated restrictive practice categories,
practice standards, code of conduct, and incident management obligations.

Run:
    python scripts/ingest_ndis_policies.py

Idempotent — safe to re-run; existing chunks are updated in place.
"""

import asyncio
import sys
import tempfile
import traceback
from pathlib import Path

import httpx

# Government sites (ndiscommission.gov.au) sometimes use CA chains not in the
# Windows trust store. verify=False is acceptable for public PDF downloads.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal, create_tables
from ingestion.chunker import chunk_document, extract_text_from_pdf
from ingestion.embedder import upsert_chunks

# Official NDIS Commission PDFs (URLs verified May 2026)
# If auto-download fails due to government WAF, download manually and place in pdfs/ folder.
NDIS_DOCUMENTS = [
    {
        "url": "https://www.ndiscommission.gov.au/sites/default/files/2022-02/regulated-restrictive-practice-guide-rrp-20200.pdf",
        "local_filename": "regulated-restrictive-practice-guide.pdf",
        "source": "NDIS Regulated Restrictive Practices Guide",
        "category": "Restrictive Practices",
        "risk_level": "High Risk",
        "document_type": "Regulatory",
    },
    {
        "url": "https://www.ndiscommission.gov.au/sites/default/files/2024-10/ndis-practice-standards-and-quality-indicators.pdf",
        "local_filename": "ndis-practice-standards-and-quality-indicators.pdf",
        "source": "NDIS Practice Standards and Quality Indicators (Oct 2024)",
        "category": "Practice Standard",
        "risk_level": "Medium Risk",
        "document_type": "Practice Standard",
    },
    {
        "url": "https://www.ndiscommission.gov.au/sites/default/files/2024-10/Code-of-Conduct-Provider-Guidance.pdf",
        "local_filename": "Code-of-Conduct-Provider-Guidance.pdf",
        "source": "NDIS Code of Conduct — Provider Guidance (Apr 2024)",
        "category": "Code of Conduct",
        "risk_level": "Medium Risk",
        "document_type": "Code of Conduct",
    },
    {
        "url": "https://www.ndiscommission.gov.au/sites/default/files/2024-10/Code-of-Conduct-Worker-Guidance.pdf",
        "local_filename": "Code-of-Conduct-Worker-Guidance.pdf",
        "source": "NDIS Code of Conduct — Worker Guidance (Apr 2024)",
        "category": "Code of Conduct",
        "risk_level": "Medium Risk",
        "document_type": "Code of Conduct",
    },
    {
        "url": "https://www.ndiscommission.gov.au/sites/default/files/2024-09/detailed-guidance-incident-management-systems-detailed-guidance-regi-20240926.pdf",
        "local_filename": "incident-management-systems-guidance.pdf",
        "source": "Incident Management Systems — Detailed Guidance (Sept 2024)",
        "category": "Reportable Incident",
        "risk_level": "High Risk",
        "document_type": "Incident Management",
    },
]

# Place manually downloaded PDFs here as fallback when auto-download is blocked
_LOCAL_PDF_DIR = Path(__file__).resolve().parent.parent / "pdfs"


async def download_with_retry(url: str, retries: int = 3) -> bytes:
    """Download URL with retries and exponential backoff. Returns raw bytes."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0),
                follow_redirects=True,
                verify=False,
            ) as client:
                resp = await client.get(url, headers=_HEADERS)
                resp.raise_for_status()
                return resp.content
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
            last_exc = exc
            wait = 2 ** attempt
            print(f"  Attempt {attempt}/{retries} failed ({type(exc).__name__}) — retrying in {wait}s...")
            await asyncio.sleep(wait)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"HTTP {exc.response.status_code} from {url}") from exc
    raise RuntimeError(f"Download failed after {retries} attempts: {last_exc}") from last_exc


async def ingest_document(doc: dict, tmp_dir: Path) -> int:
    print(f"\n[{doc['document_type']}] {doc['source']}")

    # Prefer local file — check our canonical name AND the browser's default download name
    url_basename = doc["url"].split("/")[-1]
    local_candidates = [
        _LOCAL_PDF_DIR / doc["local_filename"],
        _LOCAL_PDF_DIR / url_basename,
    ]
    local_path = next((p for p in local_candidates if p.exists()), None)

    if local_path:
        print(f"  Using local file: {local_path}")
        pdf_path = local_path
    else:
        url = doc["url"]
        print(f"  Downloading {url}...")
        content = await download_with_retry(url)
        tmp_path = tmp_dir / doc["local_filename"]
        tmp_path.write_bytes(content)
        print(f"  Downloaded {len(content):,} bytes")
        pdf_path = tmp_path

    text = extract_text_from_pdf(pdf_path)
    chunks = chunk_document(
        text=text,
        document_source=doc["source"],
        category=doc["category"],
        risk_level=doc["risk_level"],
        document_type=doc["document_type"],
    )
    print(f"  Produced {len(chunks)} chunks")

    async with AsyncSessionLocal() as db:
        count = await upsert_chunks(chunks, db)

    print(f"  Stored {count} chunks")
    return count


async def main() -> None:
    print("=== NDIS Policy Document Ingestion ===")
    print(f"Documents to ingest: {len(NDIS_DOCUMENTS)}")
    print(f"Local PDF fallback dir: {_LOCAL_PDF_DIR}")

    print("\nInitialising database tables...")
    await create_tables()

    total_chunks = 0
    failed: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for doc in NDIS_DOCUMENTS:
            try:
                count = await ingest_document(doc, tmp_path)
                total_chunks += count
            except Exception as exc:
                print(f"  ERROR [{type(exc).__name__}]: {exc}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                failed.append(doc)

    print(f"\n{'='*40}")
    print(f"Ingestion complete — {total_chunks} total chunks stored")

    if failed:
        print(f"\n{len(failed)} document(s) failed to auto-download.", file=sys.stderr)
        print("\nManual download fallback:", file=sys.stderr)
        print(f"  1. Create folder:  mkdir pdfs", file=sys.stderr)
        print(f"  2. Download each PDF in your browser and save to the pdfs/ folder:", file=sys.stderr)
        for doc in failed:
            url_basename = doc["url"].split("/")[-1]
            print(f"     Save as: pdfs/{doc['local_filename']}  (or pdfs/{url_basename})", file=sys.stderr)
            print(f"     URL:     {doc['url']}", file=sys.stderr)
        print(f"\n  3. Re-run:  python scripts/ingest_ndis_policies.py", file=sys.stderr)
        print(f"     (Script auto-detects files in pdfs/ and skips download)", file=sys.stderr)
    else:
        print("All documents ingested successfully.")

    print("\nRun 'make audit-chunks' to verify counts by document type.")


if __name__ == "__main__":
    asyncio.run(main())
