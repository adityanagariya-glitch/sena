"""CLI script to ingest NDIS policy PDFs (or sample text) into pgvector.

Usage:
    # Ingest a real PDF
    python scripts/ingest_docs.py --pdf path/to/guide.pdf \
        --category "Chemical Restraint" \
        --source "NDIS Regulated Restrictive Practices Guide 2023" \
        --risk "High Risk" --document-type "Regulatory"

    # Ingest PDF directly from URL
    python scripts/ingest_docs.py --url https://example.com/guide.pdf \
        --category "Chemical Restraint" \
        --source "NDIS Guide 2024" \
        --risk "High Risk" --document-type "Regulatory"

    # Ingest built-in sample data (no PDF needed — good for testing Step 2)
    python scripts/ingest_docs.py --sample
"""

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

import httpx

# Allow running from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal, create_tables
from ingestion.chunker import chunk_document, chunk_text, extract_text_from_pdf
from ingestion.embedder import upsert_chunks

# ---------------------------------------------------------------------------
# Sample NDIS policy text for testing without a real PDF
# ---------------------------------------------------------------------------

SAMPLE_POLICIES: list[dict] = [
    {
        "category": "Chemical Restraint",
        "document_source": "NDIS Regulated Restrictive Practices Guide 2023 (sample)",
        "risk_level": "High Risk",
        "text": (
            "Chemical restraint means the use of medication or chemical substance for the "
            "primary purpose of influencing a person's behaviour. It does not include the "
            "use of medication prescribed by a medical practitioner for the treatment of a "
            "diagnosed mental disorder, physical illness or physical condition. "
            "PRN (as-needed) medication may constitute chemical restraint if administered "
            "primarily to manage behaviour rather than to treat a medical condition. "
            "Providers must ensure that any use of chemical restraint is authorised in a "
            "behaviour support plan (BSP) developed by a registered behaviour support practitioner. "
            "Unauthorised chemical restraint must be reported to the NDIS Commission within "
            "five business days of the provider becoming aware of the incident."
        ),
    },
    {
        "category": "Seclusion",
        "document_source": "NDIS Regulated Restrictive Practices Guide 2023 (sample)",
        "risk_level": "High Risk",
        "text": (
            "Seclusion means the sole confinement of a person with disability in a room or "
            "physical space at any hour of the day or night where voluntary exit is prevented "
            "or not facilitated, or it is implied that voluntary exit is not permitted. "
            "Locking a participant's bedroom door from the outside, placing a person in a "
            "timeout room, or preventing a person from leaving a designated area all "
            "constitute seclusion under the NDIS Rules. "
            "Seclusion must never be used as punishment and must only occur as a last resort "
            "when there is an imminent risk of harm. All uses of seclusion must be recorded, "
            "reviewed, and reported to the NDIS Commission."
        ),
    },
    {
        "category": "Physical Restraint",
        "document_source": "NDIS Regulated Restrictive Practices Guide 2023 (sample)",
        "risk_level": "High Risk",
        "text": (
            "Physical restraint means the use or action of physical force to prevent, "
            "restrict or subdue movement of a person's body, or part of their body, for the "
            "primary purpose of influencing a person's behaviour. "
            "This includes holding a person's arms, guiding them forcefully to a seat, or "
            "using physical blocking techniques to prevent movement. "
            "Physical restraint does not include the use of physical force or assistance that "
            "is necessary for medical or surgical procedures, or physical assistance provided "
            "as part of care. "
            "All physical restraint must be documented immediately after use, including "
            "duration, type of hold used, and staff members present."
        ),
    },
    {
        "category": "Mechanical Restraint",
        "document_source": "NDIS Regulated Restrictive Practices Guide 2023 (sample)",
        "risk_level": "High Risk",
        "text": (
            "Mechanical restraint means the use of a device to prevent, restrict or subdue "
            "movement of a person's body, or part of their body, for the primary purpose of "
            "influencing a person's behaviour. "
            "Examples include lap belts on wheelchairs used to restrict movement rather than "
            "for postural support, mittens or gloves to prevent scratching, harnesses used "
            "in vehicles beyond what is required by road safety law, and bed rails used to "
            "prevent a person from getting out of bed. "
            "Mechanical restraint must be clearly distinguished from assistive technology "
            "used for therapeutic or safety purposes not related to behaviour management."
        ),
    },
    {
        "category": "Environmental Restraint",
        "document_source": "NDIS Regulated Restrictive Practices Guide 2023 (sample)",
        "risk_level": "Medium Risk",
        "text": (
            "Environmental restraint means the modification of an environment for the "
            "primary purpose of restricting a person's free movement or access to items "
            "or areas. "
            "Examples include placing locks on cupboards, fridges, or rooms to prevent "
            "access; removing items from a person's reach; using alarm systems to alert "
            "staff when a person attempts to leave; or configuring door handles in a way "
            "that makes exit difficult. "
            "Environmental restraint must be distinguished from reasonable safety measures "
            "such as pool fencing or stair gates that are standard safety features in any "
            "household. The primary purpose test — whether the modification is primarily "
            "about behaviour management — is the key determinant."
        ),
    },
]


async def ingest_sample() -> None:
    print("Initialising DB tables...")
    await create_tables()
    async with AsyncSessionLocal() as db:
        for policy in SAMPLE_POLICIES:
            chunks = chunk_text(
                text=policy["text"],
                document_source=policy["document_source"],
                category=policy["category"],
                risk_level=policy["risk_level"],
            )
            count = await upsert_chunks(chunks, db)
            print(f"  [{policy['category']}] stored {count} chunk(s)")
    print("Sample ingestion complete.")


async def ingest_pdf(
    pdf_path: str, category: str, source: str, risk: str, document_type: str = "Regulatory"
) -> None:
    path = Path(pdf_path)
    if not path.exists() or not path.is_file():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    print(f"Extracting text from {pdf_path}...")
    await create_tables()
    text = extract_text_from_pdf(pdf_path)
    chunks = chunk_document(text, source, category, risk, document_type=document_type)
    print(f"Produced {len(chunks)} chunks. Embedding and storing...")
    async with AsyncSessionLocal() as db:
        count = await upsert_chunks(chunks, db)
    print(f"Done — {count} chunks stored from {pdf_path}.")


async def ingest_url(
    url: str, category: str, source: str, risk: str, document_type: str = "Regulatory"
) -> None:
    print(f"Downloading {url}...")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/pdf,*/*",
            })
            resp.raise_for_status()
            tmp_path.write_bytes(resp.content)
        print(f"Downloaded {len(resp.content):,} bytes → {tmp_path}")
        await ingest_pdf(str(tmp_path), category, source, risk, document_type)
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest NDIS policy documents into pgvector.")
    parser.add_argument("--sample", action="store_true", help="Ingest built-in sample policies")
    parser.add_argument("--pdf", help="Path to a PDF file to ingest")
    parser.add_argument("--url", help="URL to download PDF from and ingest")
    parser.add_argument("--category", help="Practice category (e.g. 'Chemical Restraint')")
    parser.add_argument("--source", help="Document source label")
    parser.add_argument("--risk", default="High Risk", help="Risk level (default: High Risk)")
    parser.add_argument(
        "--document-type",
        default="Regulatory",
        help="Document type tag: Regulatory | Practice Standard | Code of Conduct | Incident Management | Behaviour Support",
    )
    args = parser.parse_args()

    if args.sample:
        asyncio.run(ingest_sample())
    elif args.pdf:
        if not args.category or not args.source:
            parser.error("--category and --source are required with --pdf")
        asyncio.run(ingest_pdf(args.pdf, args.category, args.source, args.risk, args.document_type))
    elif args.url:
        if not args.category or not args.source:
            parser.error("--category and --source are required with --url")
        asyncio.run(ingest_url(args.url, args.category, args.source, args.risk, args.document_type))
    else:
        parser.print_help()
