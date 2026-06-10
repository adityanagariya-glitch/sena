"""
test_pipeline.py
----------------
End-to-end test script for the Document Extraction Module.

Downloads real publicly available identity-like documents from the internet
and runs them through the full pipeline (converter → extractor → result).

Usage:
    python test_pipeline.py                  # run all tests
    python test_pipeline.py --case pdf_clean # run one specific case
    python test_pipeline.py --list           # list all test case names

Requirements:
    - AWS credentials configured (env vars or ~/.aws/credentials)
    - pip install -r requirements.txt
    - All five module files in the same directory
"""

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import requests
from PIL import Image, ImageDraw, ImageFont
from docx import Document as DocxDocument

# ── Module under test ────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import config
from scripts.converter import detect_format, DocumentFormat
from scripts.models import ExtractionResult
from scripts.pipeline import run

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_pipeline")

# ── Colour helpers (terminal) ─────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):  return f"{GREEN}✓ PASS{RESET}  {msg}"
def fail(msg): return f"{RED}✗ FAIL{RESET}  {msg}"
def warn(msg): return f"{YELLOW}⚠ WARN{RESET}  {msg}"
def info(msg): return f"{CYAN}ℹ INFO{RESET}  {msg}"


# ─────────────────────────────────────────────────────────────────────────────
# Test case definition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    """Defines a single test scenario."""

    name: str
    description: str

    # --- Input source (exactly one must be set) ---
    url: Optional[str] = None           # download from internet
    generate: Optional[str] = None      # local generation function name
    local_path: Optional[str] = None    # pre-existing local file

    # --- Expected outcomes ---
    expect_format: Optional[DocumentFormat] = None   # None = don't check
    expect_fields_not_null: list[str] = field(default_factory=list)
    expect_all_null: bool = False        # True for total-failure cases
    expect_pipeline_raises: bool = False # True when run() itself should raise

    # --- File metadata ---
    filename: str = "test_doc.jpg"       # saved as this name in temp dir
    skip_reason: Optional[str] = None    # non-None = skip this test


# ─────────────────────────────────────────────────────────────────────────────
# Local file generators
# These create synthetic test files programmatically so tests are self-contained
# ─────────────────────────────────────────────────────────────────────────────

def _generate_clean_jpg(path: Path) -> None:
    """A clean, high-contrast synthetic passport-style JPG."""
    img = Image.new("RGB", (800, 500), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)

    try:
        font_h = ImageFont.load_default(size=28)
        font_b = ImageFont.load_default(size=20)
    except TypeError:
        font_h = font_b = ImageFont.load_default()

    draw.rectangle([30, 30, 770, 470], outline=(0, 0, 128), width=3)
    draw.text((40, 50),  "REPUBLIC OF TESTLAND — PASSPORT",       font=font_h, fill=(0, 0, 128))
    draw.text((40, 110), "Passport No:   P9876543",                font=font_b, fill=(20, 20, 20))
    draw.text((40, 150), "Surname:       SMITH",                   font=font_b, fill=(20, 20, 20))
    draw.text((40, 190), "Given Names:   JOHN MICHAEL",            font=font_b, fill=(20, 20, 20))
    draw.text((40, 230), "Date of Issue: 15/03/2019",              font=font_b, fill=(20, 20, 20))
    draw.text((40, 270), "Date of Expiry:15/03/2029",              font=font_b, fill=(20, 20, 20))
    draw.text((40, 310), "Address:       42 Harbour View, Sydney NSW 2000", font=font_b, fill=(20, 20, 20))
    img.save(str(path), format="JPEG", quality=95)


def _generate_clean_png(path: Path) -> None:
    """PNG version of the synthetic passport — tests RGBA stripping."""
    img = Image.new("RGBA", (800, 500), color=(245, 245, 240, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_h = ImageFont.load_default(size=28)
        font_b = ImageFont.load_default(size=20)
    except TypeError:
        font_h = font_b = ImageFont.load_default()

    draw.rectangle([30, 30, 770, 470], outline=(0, 0, 128, 255), width=3)
    draw.text((40, 50),  "REPUBLIC OF TESTLAND — PASSPORT",       font=font_h, fill=(0, 0, 128, 255))
    draw.text((40, 110), "Passport No:   P9876543",                font=font_b, fill=(20, 20, 20, 255))
    draw.text((40, 150), "Full Name:     JOHN MICHAEL SMITH",      font=font_b, fill=(20, 20, 20, 255))
    draw.text((40, 190), "Issue Date:    15/03/2019",              font=font_b, fill=(20, 20, 20, 255))
    draw.text((40, 230), "Expiry Date:   15/03/2029",              font=font_b, fill=(20, 20, 20, 255))
    draw.text((40, 270), "Address:       42 Harbour View, Sydney NSW 2000", font=font_b, fill=(20, 20, 20, 255))
    img.save(str(path), format="PNG")


def _generate_low_quality_jpg(path: Path) -> None:
    """
    Heavily compressed, small JPG — simulates a bad phone scan.
    Tests model performance on low-quality input.
    """
    img = Image.new("RGB", (300, 200), color=(200, 200, 190))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=12)
    except TypeError:
        font = ImageFont.load_default()

    draw.text((5, 5),   "PASSPORT",               font=font, fill=(0, 0, 0))
    draw.text((5, 25),  "No: P9876543",            font=font, fill=(0, 0, 0))
    draw.text((5, 45),  "Name: JOHN SMITH",        font=font, fill=(0, 0, 0))
    draw.text((5, 65),  "Issue: 15/03/2019",       font=font, fill=(0, 0, 0))
    draw.text((5, 85),  "Expiry: 15/03/2029",      font=font, fill=(0, 0, 0))
    draw.text((5, 105), "Addr: 42 Harbour View",   font=font, fill=(0, 0, 0))
    # Save at very low quality to simulate compression artefacts
    img.save(str(path), format="JPEG", quality=10)


def _generate_rotated_jpg(path: Path) -> None:
    """
    90-degree rotated image — simulates a sideways phone upload.
    Model should still read it; tests robustness to orientation.
    """
    img = Image.new("RGB", (500, 800), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:
        font = ImageFont.load_default()

    draw.text((20, 20),  "PASSPORT",                              font=font, fill=(0, 0, 128))
    draw.text((20, 60),  "Passport No: P9876543",                 font=font, fill=(20, 20, 20))
    draw.text((20, 100), "Name: JOHN MICHAEL SMITH",              font=font, fill=(20, 20, 20))
    draw.text((20, 140), "Issue Date: 15/03/2019",                font=font, fill=(20, 20, 20))
    draw.text((20, 180), "Expiry Date: 15/03/2029",               font=font, fill=(20, 20, 20))
    draw.text((20, 220), "Address: 42 Harbour View, Sydney",      font=font, fill=(20, 20, 20))
    rotated = img.rotate(90, expand=True)
    rotated.save(str(path), format="JPEG", quality=85)


def _generate_partial_fields_jpg(path: Path) -> None:
    """
    Document with only some fields present — no address, no issue date.
    Expects partial extraction status.
    """
    img = Image.new("RGB", (800, 400), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:
        font = ImageFont.load_default()

    draw.text((40, 40),  "DRIVER LICENCE",             font=font, fill=(0, 80, 0))
    draw.text((40, 90),  "Licence No: DL12345678",     font=font, fill=(20, 20, 20))
    draw.text((40, 130), "Name: JANE ANNE DOE",         font=font, fill=(20, 20, 20))
    draw.text((40, 170), "Expiry: 22/08/2026",         font=font, fill=(20, 20, 20))
    # No address, no issue date — should return partial
    img.save(str(path), format="JPEG", quality=90)


def _generate_no_fields_jpg(path: Path) -> None:
    """
    Image with no recognisable identity fields — a blank form header.
    Expects failed status with all nulls.
    """
    img = Image.new("RGB", (600, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=22)
    except TypeError:
        font = ImageFont.load_default()

    draw.text((40, 100), "OFFICIAL GOVERNMENT FORM",  font=font, fill=(100, 100, 100))
    draw.text((40, 150), "Please complete all sections below.", font=font, fill=(100, 100, 100))
    img.save(str(path), format="JPEG", quality=90)


def _generate_clean_pdf(path: Path) -> None:
    """
    Minimal single-page PDF with passport fields.
    Uses pymupdf to create the PDF programmatically.
    """
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    lines = [
        ("REPUBLIC OF TESTLAND — PASSPORT", 60, 80, 20),
        ("Passport No:   P9876543",          60, 130, 14),
        ("Full Name:     JOHN MICHAEL SMITH",60, 160, 14),
        ("Date of Issue: 15/03/2019",        60, 190, 14),
        ("Date of Expiry:15/03/2029",        60, 220, 14),
        ("Address:       42 Harbour View, Sydney NSW 2000", 60, 250, 14),
    ]

    for text, x, y, size in lines:
        page.insert_text(
            fitz.Point(x, y),
            text,
            fontsize=size,
            color=(0, 0, 0),
        )

    doc.save(str(path))
    doc.close()


def _generate_multipage_pdf(path: Path) -> None:
    """
    PDF with fields only on page 2 — converter uses page 0 only.
    Expects failed/partial result since page 0 has no fields.
    Tests that the single-page extraction assumption holds.
    """
    import fitz
    doc = fitz.open()

    # Page 0 — cover page, no fields
    page0 = doc.new_page(width=595, height=842)
    page0.insert_text(fitz.Point(60, 100), "DOCUMENT COVER PAGE", fontsize=18)
    page0.insert_text(fitz.Point(60, 140), "Personal details on next page.", fontsize=12)

    # Page 1 — has the actual fields (should NOT be extracted)
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text(fitz.Point(60, 80),  "Passport No: P9876543",       fontsize=14)
    page1.insert_text(fitz.Point(60, 110), "Name: JOHN SMITH",             fontsize=14)
    page1.insert_text(fitz.Point(60, 140), "Issue: 15/03/2019",            fontsize=14)
    page1.insert_text(fitz.Point(60, 170), "Expiry: 15/03/2029",           fontsize=14)
    page1.insert_text(fitz.Point(60, 200), "Address: 42 Harbour View",     fontsize=14)

    doc.save(str(path))
    doc.close()


def _generate_clean_docx(path: Path) -> None:
    """
    DOCX with all 5 fields clearly labelled — clean extraction case.
    """
    doc = DocxDocument()
    doc.add_heading("REPUBLIC OF TESTLAND — PASSPORT", level=1)
    doc.add_paragraph("Passport No:    P9876543")
    doc.add_paragraph("Full Name:      JOHN MICHAEL SMITH")
    doc.add_paragraph("Date of Issue:  15/03/2019")
    doc.add_paragraph("Date of Expiry: 15/03/2029")
    doc.add_paragraph("Address:        42 Harbour View, Sydney NSW 2000, Australia")
    doc.save(str(path))


def _generate_empty_docx(path: Path) -> None:
    """
    DOCX with no text — converter should raise RuntimeError.
    Pipeline should return failed result, not crash.
    """
    doc = DocxDocument()
    # Add a paragraph with only whitespace — should be treated as empty
    doc.add_paragraph("   ")
    doc.save(str(path))


def _generate_date_format_variants_jpg(path: Path) -> None:
    """
    Document with dates in non-standard formats.
    Tests that the model normalises them correctly to DD/MM/YYYY.
    """
    img = Image.new("RGB", (800, 450), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:
        font = ImageFont.load_default()

    draw.text((40, 40),  "PASSPORT",                              font=font, fill=(0, 0, 128))
    draw.text((40, 90),  "No: P9876543",                          font=font, fill=(20, 20, 20))
    draw.text((40, 130), "Name: JOHN MICHAEL SMITH",              font=font, fill=(20, 20, 20))
    draw.text((40, 170), "Issue Date: March 15, 2019",            font=font, fill=(20, 20, 20))  # long form
    draw.text((40, 210), "Expiry Date: 2029-03-15",               font=font, fill=(20, 20, 20))  # ISO format
    draw.text((40, 250), "Address: 42 Harbour View, Sydney",      font=font, fill=(20, 20, 20))
    img.save(str(path), format="JPEG", quality=90)


def _generate_non_latin_jpg(path: Path) -> None:
    """
    Document mixing English labels with non-Latin name — tests multilingual.
    Pillow default font won't render non-Latin glyphs but the model sees the image.
    """
    img = Image.new("RGB", (800, 450), color=(245, 245, 240))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:
        font = ImageFont.load_default()

    draw.text((40, 40),  "PASSPORT / पासपोर्ट",                  font=font, fill=(0, 0, 128))
    draw.text((40, 90),  "Passport No: A1234567",                 font=font, fill=(20, 20, 20))
    draw.text((40, 130), "Name: SHARMA RAJESH KUMAR",             font=font, fill=(20, 20, 20))
    draw.text((40, 170), "Issue: 10/06/2020",                     font=font, fill=(20, 20, 20))
    draw.text((40, 210), "Expiry: 09/06/2030",                    font=font, fill=(20, 20, 20))
    draw.text((40, 250), "Address: 14 MG Road, Bengaluru 560001", font=font, fill=(20, 20, 20))
    img.save(str(path), format="JPEG", quality=90)


GENERATORS = {
    "clean_jpg":              _generate_clean_jpg,
    "clean_png":              _generate_clean_png,
    "low_quality_jpg":        _generate_low_quality_jpg,
    "rotated_jpg":            _generate_rotated_jpg,
    "partial_fields_jpg":     _generate_partial_fields_jpg,
    "no_fields_jpg":          _generate_no_fields_jpg,
    "clean_pdf":              _generate_clean_pdf,
    "multipage_pdf":          _generate_multipage_pdf,
    "clean_docx":             _generate_clean_docx,
    "empty_docx":             _generate_empty_docx,
    "date_format_variants":   _generate_date_format_variants_jpg,
    "non_latin_jpg":          _generate_non_latin_jpg,
}


# ─────────────────────────────────────────────────────────────────────────────
# Test case registry
# ─────────────────────────────────────────────────────────────────────────────

TEST_CASES: list[TestCase] = [

    # ── JPG / PNG ─────────────────────────────────────────────────────────────

    TestCase(
        name="clean_jpg",
        description="Clean synthetic JPG passport — all 5 fields present",
        generate="clean_jpg",
        filename="passport_clean.jpg",
        expect_format=DocumentFormat.IMAGE,

        expect_fields_not_null=["document_no", "name", "issue_date", "expiry_date", "address"],
    ),

    TestCase(
        name="clean_png_rgba",
        description="RGBA PNG — tests alpha-channel stripping before JPEG encode",
        generate="clean_png",
        filename="passport_rgba.png",
        expect_format=DocumentFormat.IMAGE,

        expect_fields_not_null=["document_no", "name"],
    ),

    TestCase(
        name="low_quality_jpg",
        description="Heavily compressed small JPG — simulates bad phone scan",
        generate="low_quality_jpg",
        filename="passport_lowq.jpg",
        expect_format=DocumentFormat.IMAGE,

    ),

    TestCase(
        name="rotated_jpg",
        description="90-degree rotated JPG — simulates sideways upload",
        generate="rotated_jpg",
        filename="passport_rotated.jpg",
        expect_format=DocumentFormat.IMAGE,

    ),

    TestCase(
        name="partial_fields_jpg",
        description="Licence with only 3 fields — no address, no issue date",
        generate="partial_fields_jpg",
        filename="licence_partial.jpg",
        expect_format=DocumentFormat.IMAGE,

        expect_fields_not_null=["document_no", "name", "expiry_date"],
    ),

    TestCase(
        name="no_fields_jpg",
        description="Blank form header — no identity fields present",
        generate="no_fields_jpg",
        filename="blank_form.jpg",
        expect_format=DocumentFormat.IMAGE,

        expect_all_null=True,
    ),

    TestCase(
        name="date_format_variants",
        description="Dates in long-form and ISO format — tests DD/MM/YYYY normalisation",
        generate="date_format_variants",
        filename="passport_dates.jpg",
        expect_format=DocumentFormat.IMAGE,

        expect_fields_not_null=["issue_date", "expiry_date"],
    ),

    TestCase(
        name="non_latin_name",
        description="English labels, Latin-transliterated Indian name — multilingual test",
        generate="non_latin_jpg",
        filename="passport_india.jpg",
        expect_format=DocumentFormat.IMAGE,

        expect_fields_not_null=["document_no", "name"],
    ),

    # ── PDF ───────────────────────────────────────────────────────────────────

    TestCase(
        name="clean_pdf",
        description="Single-page PDF with all 5 fields — standard case",
        generate="clean_pdf",
        filename="passport_clean.pdf",
        expect_format=DocumentFormat.PDF,

        expect_fields_not_null=["document_no", "name", "issue_date", "expiry_date", "address"],
    ),

    TestCase(
        name="multipage_pdf",
        description="Fields only on page 2 — converter uses page 0 only, expects partial/failed",
        generate="multipage_pdf",
        filename="passport_multipage.pdf",
        expect_format=DocumentFormat.PDF,

    ),

    # ── DOCX ──────────────────────────────────────────────────────────────────

    TestCase(
        name="clean_docx",
        description="DOCX with all 5 fields — tests text-render pipeline",
        generate="clean_docx",
        filename="passport_clean.docx",
        expect_format=DocumentFormat.DOCX,

        expect_fields_not_null=["document_no", "name", "issue_date", "expiry_date", "address"],
    ),

    TestCase(
        name="empty_docx",
        description="DOCX with only whitespace — converter should fail gracefully",
        generate="empty_docx",
        filename="passport_empty.docx",
        expect_format=DocumentFormat.DOCX,

        expect_all_null=True,
    ),

    # ── Format detection edge cases ───────────────────────────────────────────

    TestCase(
        name="unsupported_extension",
        description="File with .txt extension — detect_format should raise ValueError",
        generate="clean_jpg",          # create a valid image but rename to .txt
        filename="document.txt",
        expect_format=None,
        expect_pipeline_raises=True,
    ),

    # ── Real internet samples ─────────────────────────────────────────────────
    # These are publicly available sample/specimen documents used for testing.
    # All are government specimen or openly licensed sample documents.

    TestCase(
        name="internet_pdf_sample",
        description="Real PDF from internet — Australian specimen passport (Wikimedia Commons)",
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/b/b1/Australian_Passport_Blank_Data_Page.jpg/800px-Australian_Passport_Blank_Data_Page.jpg",
        filename="aus_passport_specimen.jpg",
        expect_format=DocumentFormat.IMAGE,
        # Specimen passport — some fields may be blank/placeholder

        skip_reason=None,
    ),

    TestCase(
        name="internet_licence_sample",
        description="Real image from internet — US specimen driver licence (Wikimedia Commons)",
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Florida_Driver%27s_License_Version_5.jpg/800px-Florida_Driver%27s_License_Version_5.jpg",
        filename="us_licence_specimen.jpg",
        expect_format=DocumentFormat.IMAGE,

        skip_reason=None,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Test runner
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    passed: bool
    skipped: bool = False
    skip_reason: str = ""
    failures: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    extraction_result: Optional[ExtractionResult] = None


def _download_file(url: str, dest: Path, timeout: int = 30) -> bool:
    """Download a file from URL to dest. Returns True on success."""
    try:
        logger.info("Downloading: %s", url)
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info("Downloaded %d bytes → %s", dest.stat().st_size, dest.name)
        return True
    except Exception as exc:
        logger.warning("Download failed for %s: %s", url, exc)
        return False


def _assert_result(
    case: TestCase,
    result: ExtractionResult,
    failures: list[str],
) -> None:
    """Run all assertions on an ExtractionResult. Appends failure messages."""

    # Specific fields not null
    for field_name in case.expect_fields_not_null:
        val = getattr(result, field_name, None)
        if val is None:
            failures.append(f"Field '{field_name}' expected non-null but got null")

    # All fields null
    if case.expect_all_null:
        not_null = [
            f for f in ["document_no", "name", "issue_date", "expiry_date", "address"]
            if getattr(result, f) is not None
        ]
        if not_null:
            failures.append(f"Expected all fields null but these were set: {not_null}")

    # Date format validation for non-null date fields
    import re
    date_pattern = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    for date_field in ("issue_date", "expiry_date"):
        val = getattr(result, date_field)
        if val is not None and not date_pattern.match(val):
            failures.append(
                f"Date field '{date_field}' value {val!r} "
                f"does not match DD/MM/YYYY format"
            )

    # to_api_response() always has all 5 keys
    api_resp = result.to_api_response()
    required_keys = {
        "document_no", "name", "issue_date", "expiry_date", "address",
    }
    missing_keys = required_keys - set(api_resp.keys())
    if missing_keys:
        failures.append(f"to_api_response() missing keys: {missing_keys}")


def run_test(case: TestCase, work_dir: Path) -> TestResult:
    """Execute a single test case and return its result."""

    t0 = time.monotonic()

    # Skip?
    if case.skip_reason:
        return TestResult(
            name=case.name,
            passed=True,
            skipped=True,
            skip_reason=case.skip_reason,
            elapsed=0.0,
        )

    failures: list[str] = []
    file_path = work_dir / case.filename

    # ── Prepare input file ────────────────────────────────────────────────────
    if case.url:
        ok_dl = _download_file(case.url, file_path)
        if not ok_dl:
            return TestResult(
                name=case.name,
                passed=False,
                skipped=True,
                skip_reason="Download failed — skipping (network issue)",
                elapsed=time.monotonic() - t0,
            )

    elif case.generate:
        gen_fn = GENERATORS.get(case.generate)
        if gen_fn is None:
            return TestResult(
                name=case.name,
                passed=False,
                failures=[f"Unknown generator: {case.generate!r}"],
                elapsed=time.monotonic() - t0,
            )
        # Generate into a temp jpg first then copy to final filename
        # (some generators produce a specific format regardless of filename)
        gen_fn(file_path)

    elif case.local_path:
        shutil.copy(case.local_path, file_path)

    else:
        return TestResult(
            name=case.name,
            passed=False,
            failures=["No input source defined (url / generate / local_path)"],
            elapsed=time.monotonic() - t0,
        )

    # ── Format detection check ────────────────────────────────────────────────
    if case.expect_format is not None and not case.expect_pipeline_raises:
        try:
            detected, _ = detect_format(file_path)
            if detected != case.expect_format:
                failures.append(
                    f"Format detection: expected {case.expect_format.value!r}, "
                    f"got {detected.value!r}"
                )
        except ValueError as exc:
            failures.append(f"Format detection raised unexpectedly: {exc}")

    # ── Pipeline run ──────────────────────────────────────────────────────────
    extraction_result = None

    if case.expect_pipeline_raises:
        raised = False
        try:
            run(file_path)
        except (ValueError, FileNotFoundError):
            raised = True
        except Exception as exc:
            failures.append(
                f"Expected ValueError/FileNotFoundError but got "
                f"{type(exc).__name__}: {exc}"
            )
            raised = True

        if not raised:
            failures.append("Expected pipeline to raise but it returned normally")

    else:
        try:
            extraction_result = run(file_path)
            _assert_result(case, extraction_result, failures)
        except Exception as exc:
            failures.append(f"Pipeline raised unexpectedly: {type(exc).__name__}: {exc}")

    elapsed = time.monotonic() - t0
    return TestResult(
        name=case.name,
        passed=len(failures) == 0,
        failures=failures,
        elapsed=elapsed,
        extraction_result=extraction_result,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests (no Bedrock calls — mock the extractor)
# ─────────────────────────────────────────────────────────────────────────────

def run_unit_tests() -> list[TestResult]:
    """
    Fast unit tests that mock Bedrock.
    These validate converter, models, and config logic in isolation.
    """
    results: list[TestResult] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # ── Unit test 1: ExtractionResult missing_fields() accuracy ──────────
        name = "unit_missing_fields_derivation"
        failures = []
        try:
            all_filled = ExtractionResult(
                document_no="P123", name="John", issue_date="01/01/2020",
                expiry_date="01/01/2030", address="123 St",
            )
            assert all_filled.missing_fields() == [], \
                f"Expected no missing fields, got {all_filled.missing_fields()}"

            partial = ExtractionResult(document_no="P123", name="John")
            expected = {"issue_date", "expiry_date", "address"}
            assert set(partial.missing_fields()) == expected, \
                f"Expected {expected}, got {partial.missing_fields()}"

            all_null = ExtractionResult()
            assert len(all_null.missing_fields()) == 5, \
                f"Expected 5 missing fields, got {all_null.missing_fields()}"

        except AssertionError as exc:
            failures.append(str(exc))
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 2: Date validator rejects bad format ────────────────────
        name = "unit_date_validator"
        failures = []
        try:
            from pydantic import ValidationError
            try:
                ExtractionResult(
                    issue_date="2020-01-01",  # ISO format — should be rejected
                )
                failures.append("Expected ValidationError for bad date format, got none")
            except ValidationError:
                pass  # correct
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 3: Empty string treated as null ─────────────────────────
        name = "unit_empty_string_as_null"
        failures = []
        try:
            r = ExtractionResult(
                document_no="  ",   # whitespace only
                name="",            # empty string
            )
            if r.document_no is not None:
                failures.append(f"document_no should be null, got {r.document_no!r}")
            if r.name is not None:
                failures.append(f"name should be null, got {r.name!r}")
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 4: to_api_response() always has 5 keys ─────────────────
        name = "unit_api_response_shape"
        failures = []
        try:
            r = ExtractionResult()
            api = r.to_api_response()
            expected_keys = {
                "document_no", "name", "issue_date", "expiry_date", "address",
            }
            missing = expected_keys - set(api.keys())
            extra   = set(api.keys()) - expected_keys
            if missing:
                failures.append(f"Missing keys in to_api_response(): {missing}")
            if extra:
                failures.append(f"Extra keys in to_api_response(): {extra}")
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 5: missing_fields() accuracy ───────────────────────────
        name = "unit_missing_fields"
        failures = []
        try:
            r = ExtractionResult(
                document_no="P123",
                name="John",
            )
            missing = r.missing_fields()
            expected_missing = {"issue_date", "expiry_date", "address"}
            if set(missing) != expected_missing:
                failures.append(f"missing_fields() returned {missing}, expected {expected_missing}")
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 6: converter rejects unsupported extension ──────────────
        name = "unit_unsupported_extension"
        failures = []
        try:
            fake = tmp_path / "doc.xyz"
            fake.write_bytes(b"fake content")
            try:
                detect_format(fake)
                failures.append("Expected ValueError for .xyz extension, got none")
            except ValueError:
                pass  # correct
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 7: PDF page 0 extraction with mocked Bedrock ───────────
        name = "unit_pdf_mock_bedrock"
        failures = []
        try:
            pdf_path = tmp_path / "mock_passport.pdf"
            _generate_clean_pdf(pdf_path)

            mock_response = json.dumps({
                "document_no": "P9876543",
                "name": "JOHN MICHAEL SMITH",
                "issue_date": "15/03/2019",
                "expiry_date": "15/03/2029",
                "address": "42 Harbour View, Sydney NSW 2000",
            })

            mock_tuple = (mock_response, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0})
            with patch("scripts.extractor._call_bedrock", return_value=mock_tuple):
                result = run(pdf_path)

            if result.document_no != "P9876543":
                failures.append(f"document_no mismatch: {result.document_no!r}")
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 8: Bedrock returns markdown-fenced JSON ────────────────
        name = "unit_markdown_fence_stripping"
        failures = []
        try:
            pdf_path = tmp_path / "mock_passport2.pdf"
            _generate_clean_pdf(pdf_path)

            fenced_response = (
                "```json\n"
                '{"document_no":"P111","name":"Jane","issue_date":"01/01/2021",'
                '"expiry_date":"01/01/2031","address":"1 Test St"}\n'
                "```"
            )

            fenced_tuple = (fenced_response, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0})
            with patch("scripts.extractor._call_bedrock", return_value=fenced_tuple):
                result = run(pdf_path)

            if result.document_no != "P111":
                failures.append(f"document_no mismatch after fence strip: {result.document_no!r}")
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 9: Bedrock returns garbage — pipeline returns failed ────
        name = "unit_garbage_response"
        failures = []
        try:
            jpg_path = tmp_path / "mock_garbage.jpg"
            _generate_clean_jpg(jpg_path)

            garbage_tuple = ("I cannot extract that.", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0})
            with patch("scripts.extractor._call_bedrock", return_value=garbage_tuple):
                result = run(jpg_path)

            if result.missing_fields() != ["document_no", "name", "issue_date", "expiry_date", "address"]:
                failures.append(f"Expected all fields null, got {result.to_api_response()}")
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

        # ── Unit test 10: Bedrock returns extra keys — they are dropped ───────
        name = "unit_extra_keys_dropped"
        failures = []
        try:
            jpg_path = tmp_path / "mock_extra.jpg"
            _generate_clean_jpg(jpg_path)

            response_with_extras = json.dumps({
                "document_no": "P123",
                "name": "John Smith",
                "issue_date": "01/01/2020",
                "expiry_date": "01/01/2030",
                "address": "1 Test St",
                "nationality": "Australian",   # extra — should be dropped
                "dob": "01/01/1980",           # extra — should be dropped
            })

            extras_tuple = (response_with_extras, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "latency_ms": 0})
            with patch("scripts.extractor._call_bedrock", return_value=extras_tuple):
                result = run(jpg_path)

            api = result.to_api_response()
            if "nationality" in api:
                failures.append("Extra key 'nationality' leaked into API response")
            if "dob" in api:
                failures.append("Extra key 'dob' leaked into API response")
            if result.missing_fields():
                failures.append(f"Expected all 5 fields set, missing: {result.missing_fields()}")
        except Exception as exc:
            failures.append(f"Unexpected: {exc}")
        results.append(TestResult(name=name, passed=not failures, failures=failures, elapsed=0))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def print_report(all_results: list[TestResult]) -> None:
    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  EXTRACTION MODULE — TEST REPORT{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}\n")

    passed = skipped = failed = 0

    for r in all_results:
        if r.skipped:
            print(warn(f"[SKIP] {r.name}  ({r.skip_reason})"))
            skipped += 1
            continue

        if r.passed:
            timing = f"{r.elapsed:.2f}s"
            status_str = ""
            if r.extraction_result:
                status_str = (
                    f"  [{5 - len(r.extraction_result.missing_fields())}/5 fields]"
                )
            print(ok(f"{r.name}{status_str}  ({timing})"))
            passed += 1
        else:
            print(fail(f"{r.name}  ({r.elapsed:.2f}s)"))
            for f_msg in r.failures:
                print(f"         {RED}→ {f_msg}{RESET}")
            if r.extraction_result:
                print(f"         {CYAN}→ API response: "
                      f"{json.dumps(r.extraction_result.to_api_response(), indent=None)}{RESET}")
            failed += 1

    total = passed + skipped + failed
    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(
        f"  Total: {total}  |  "
        f"{GREEN}Passed: {passed}{RESET}  |  "
        f"{YELLOW}Skipped: {skipped}{RESET}  |  "
        f"{RED}Failed: {failed}{RESET}"
    )
    print(f"{BOLD}{'─' * 70}{RESET}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Local file / folder helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_local_file(file_path: Path) -> TestResult:
    """Run the pipeline on a single user-supplied file. No assertions — just shows output."""
    t0 = time.monotonic()
    try:
        result = run(file_path)
    except (FileNotFoundError, ValueError) as exc:
        return TestResult(name=file_path.name, passed=False,
                          failures=[str(exc)], elapsed=time.monotonic() - t0)
    return TestResult(name=file_path.name, passed=True,
                      elapsed=time.monotonic() - t0, extraction_result=result)


def print_local_result(file_path: Path, result: TestResult) -> None:
    """Pretty-print extraction output for a user-supplied file."""
    print(f"\n{BOLD}{'─' * 70}{RESET}")
    print(f"{BOLD}  {file_path.name}{RESET}")
    print(f"{BOLD}{'─' * 70}{RESET}")

    if not result.passed:
        print(f"  {RED}Error: {result.failures[0]}{RESET}\n")
        return

    r = result.extraction_result
    api = r.to_api_response()

    out_dir = Path(r"C:\Users\BAPS\Documents\SENA_text-extraction\local_test_result")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / (file_path.stem + ".json")
    out_file.write_text(json.dumps(api, indent=4), encoding="utf-8")
    print(f"  {CYAN}Saved → {out_file}{RESET}")

    fields_found = 5 - len(r.missing_fields())
    fields_colour = GREEN if fields_found == 5 else YELLOW if fields_found > 0 else RED
    print(f"\n  Fields  : {fields_colour}{fields_found}/5 extracted{RESET}"
          f"  |  Time: {result.elapsed:.2f}s\n")

    for field_name in ["document_no", "name", "issue_date", "expiry_date", "address"]:
        value = api[field_name]
        label = field_name.replace("_", " ").title().ljust(14)
        if value is not None:
            print(f"  {GREEN}✓{RESET} {label}: {value}")
        else:
            print(f"  {RED}✗{RESET} {label}: null")

    print(f"\n  {CYAN}Full JSON:{RESET}")
    print(f"  {json.dumps(api, indent=4)}\n")


def _run_with_file_or_folder(args) -> None:
    """Handle --file and --folder modes."""
    supported_exts = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".docx"}

    if args.file:
        file_path = Path(args.file)
        result = run_local_file(file_path)
        print_local_result(file_path, result)
        sys.exit(0 if result.passed else 1)

    if args.folder:
        folder = Path(args.folder)
        if not folder.exists() or not folder.is_dir():
            print(f"{RED}Folder not found: {folder}{RESET}")
            sys.exit(1)

        files = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in supported_exts
        )
        if not files:
            print(f"{YELLOW}No supported files found in: {folder}{RESET}")
            print(f"Supported: {sorted(supported_exts)}")
            sys.exit(0)

        print(f"\n{BOLD}Found {len(files)} file(s) in:{RESET} {folder}")
        all_passed = True
        for file_path in files:
            result = run_local_file(file_path)
            print_local_result(file_path, result)
            if not result.passed:
                all_passed = False
        sys.exit(0 if all_passed else 1)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Document Extraction Module — Test Runner"
    )
    parser.add_argument(
        "--file", metavar="PATH",
        help="Run pipeline on a single local file and show extracted fields",
    )
    parser.add_argument(
        "--folder", metavar="PATH",
        help="Run pipeline on every supported file in a folder",
    )
    parser.add_argument(
        "--case", metavar="NAME",
        help="Run only this specific built-in test case by name",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all available built-in test case names and exit",
    )
    parser.add_argument(
        "--unit-only", action="store_true",
        help="Run only unit tests (no Bedrock calls)",
    )
    parser.add_argument(
        "--integration-only", action="store_true",
        help="Run only integration tests (requires Bedrock credentials)",
    )
    args = parser.parse_args()

    # Route --file and --folder to dedicated handlers
    if args.file or args.folder:
        _run_with_file_or_folder(args)
        return  # _run_with_file_or_folder calls sys.exit internally

    if args.list:
        print("\nAvailable test cases:\n")
        for c in TEST_CASES:
            src = f"url={c.url[:50]}..." if c.url else f"generate={c.generate}"
            print(f"  {CYAN}{c.name:<35}{RESET}  {c.description}")
            print(f"  {'':35}  [{src}]")
        print(f"\nUnit tests: unit_status_derivation, unit_date_validator, "
              f"unit_empty_string_as_null, unit_api_response_shape, "
              f"unit_missing_fields, unit_unsupported_extension, "
              f"unit_pdf_mock_bedrock, unit_markdown_fence_stripping, "
              f"unit_garbage_response, unit_extra_keys_dropped\n")
        return

    all_results: list[TestResult] = []

    # Unit tests
    if not args.integration_only:
        print(f"\n{BOLD}Running unit tests (mocked Bedrock)...{RESET}")
        unit_results = run_unit_tests()
        all_results.extend(unit_results)

    # Integration tests
    if not args.unit_only:
        cases_to_run = TEST_CASES
        if args.case:
            cases_to_run = [c for c in TEST_CASES if c.name == args.case]
            if not cases_to_run:
                print(f"{RED}No test case named {args.case!r}. Use --list to see all.{RESET}")
                sys.exit(1)

        print(f"\n{BOLD}Running integration tests (live Bedrock calls)...{RESET}")
        print(info("Ensure AWS credentials are configured before running.\n"))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for case in cases_to_run:
                print(f"  → {case.name}: {case.description}")
                result = run_test(case, tmp_path)
                all_results.append(result)

    print_report(all_results)

    failed_count = sum(1 for r in all_results if not r.passed and not r.skipped)
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()

