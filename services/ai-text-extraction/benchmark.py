import argparse
import base64
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from http.client import HTTPException

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BENCHMARK_DIR    = Path("benchmark")
IMAGES_DIR       = BENCHMARK_DIR / "images"
METADATA_DIR     = BENCHMARK_DIR / "metadata"
GROUND_TRUTH_DIR = BENCHMARK_DIR / "ground_truth"
RESULTS_DIR      = BENCHMARK_DIR / "results"
REVIEW_FILE      = BENCHMARK_DIR / "review.html"
REPORT_FILE      = BENCHMARK_DIR / "report.json"

# Target total images to collect
TARGET_IMAGES = 60  # collect a few extra; duplicates will be filtered

# Minimum image width to filter out icons/thumbnails
MIN_IMAGE_WIDTH = 400

SUPPORTED_FORMATS = {"jpg", "jpeg", "png"}

# Wikimedia Commons categories to crawl.
# Format: (category_name, label, max_images_from_this_category)
# Categories are crawled in order; collection stops when TARGET_IMAGES is reached.
# Covers: passports (data/biodata pages), ID cards, driving licences — across many countries.
WIKIMEDIA_CATEGORIES = [
    # --- Passport biodata/data pages (richest single category) ---
    ("Passport data pages",                   "passport",        20),
    ("Passport biodata pages",                "passport",        10),

    # --- Identity card specimens ---
    ("Identity card specimens",               "id_card",         10),

    # --- Per-country passports (biodata page subcategories) ---
    ("Passports of Australia",                "passport_aus",     5),
    ("Passports of the United Kingdom",       "passport_gbr",     5),
    ("Passports of the United States",        "passport_usa",     5),
    ("Passports of India",                    "passport_ind",     5),
    ("Passports of Germany",                  "passport_deu",     5),
    ("Passports of France",                   "passport_fra",     5),
    ("Passports of Canada",                   "passport_can",     5),
    ("Passports of Japan",                    "passport_jpn",     5),
    ("Passports of China",                    "passport_chn",     5),
    ("Passports of Brazil",                   "passport_bra",     5),
    ("Passports of South Africa",             "passport_zaf",     5),
    ("Passports of Nigeria",                  "passport_nga",     5),
    ("Passports of Pakistan",                 "passport_pak",     5),
    ("Passports of Bangladesh",               "passport_bgd",     5),
    ("Passports of the Philippines",          "passport_phl",     5),
    ("Passports of Indonesia",                "passport_idn",     5),
    ("Passports of Mexico",                   "passport_mex",     5),
    ("Passports of New Zealand",              "passport_nzl",     5),
    ("Passports of Singapore",                "passport_sgp",     5),
    ("Passports of South Korea",              "passport_kor",     5),
    ("Passports of Malaysia",                 "passport_mys",     5),
    ("Passports of the Netherlands",          "passport_nld",     5),
    ("Passports of Spain",                    "passport_esp",     5),
    ("Passports of Italy",                    "passport_ita",     5),
    ("Passports of Sweden",                   "passport_swe",     5),
    ("Passports of Norway",                   "passport_nor",     5),
    ("Passports of Switzerland",              "passport_che",     5),
    ("Passports of Russia",                   "passport_rus",     5),
    ("Passports of Turkey",                   "passport_tur",     5),
    ("Passports of Saudi Arabia",             "passport_sau",     5),
    ("Passports of the United Arab Emirates", "passport_uae",     5),

    # --- Driving licence specimens ---
    ("Driving licences of the United Kingdom","driving_licence",  5),
    ("Driver's licenses of the United States","driving_licence",  5),
    ("Driver's licences of Australia",        "driving_licence",  5),
]

# Wikimedia API base
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"

# Polite delay between API requests (seconds)
REQUEST_DELAY = 0.5

# User-Agent required by Wikimedia API policy
USER_AGENT = (
    "BenchmarkDatasetBuilder/2.0 "
    "(government-id-ocr-benchmark; contact: your@email.com)"
)

HEADERS = {"User-Agent": USER_AGENT}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATIC_FIELDS = ["document_no", "name", "issue_date", "expiry_date", "address"]


def _http_get(params: dict) -> dict:
    """Call the Wikimedia API with given params. Returns parsed JSON."""
    qs  = urlencode(params)
    url = f"{WIKIMEDIA_API}?{qs}"
    time.sleep(REQUEST_DELAY)
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, HTTPException) as exc:
        logger.warning("API error: %s  url=%s", exc, url)
        raise


def _download_binary(url: str, dest: Path) -> bool:
    """Download a binary file to dest. Returns True on success."""
    time.sleep(REQUEST_DELAY)
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as exc:
        logger.warning("Download failed %s: %s", url, exc)
        if dest.exists():
            dest.unlink()
        return False


def _safe_filename(title: str) -> str:
    """Convert a Wikimedia page title to a safe local filename stem."""
    name = title.replace("File:", "").replace(" ", "_")
    name = re.sub(r"[^\w\-.]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:180]


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _mime_type(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"


# ---------------------------------------------------------------------------
# Wikimedia API helpers
# ---------------------------------------------------------------------------

def _get_category_file_titles(category: str, limit: int) -> list[str]:
    """
    Return file titles (e.g. 'File:Foo.jpg') from a Wikimedia Commons category.
    Handles pagination via 'cmcontinue'.
    """
    titles   = []
    cmcontinue = None

    while len(titles) < limit:
        params = {
            "action":      "query",
            "list":        "categorymembers",
            "cmtitle":     f"Category:{category}",
            "cmnamespace": "6",          # File namespace only
            "cmlimit":     str(min(50, limit - len(titles))),
            "format":      "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        try:
            data = _http_get(params)
        except Exception:
            break

        members = data.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members)

        cont = data.get("continue", {})
        cmcontinue = cont.get("cmcontinue")
        if not cmcontinue or not members:
            break

    return titles[:limit]


def _get_file_info(titles: list[str]) -> list[dict]:
    """
    Fetch imageinfo (url, size, mime, metadata) for a batch of file titles.
    Wikimedia API allows up to 50 titles per request.
    """
    results = []
    batch_size = 50

    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        params = {
            "action":  "query",
            "titles":  "|".join(batch),
            "prop":    "imageinfo",
            "iiprop":  "url|size|mime|extmetadata",
            "iiurlwidth": "1400",
            "format":  "json",
        }
        try:
            data = _http_get(params)
        except Exception:
            continue

        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            info_list = page.get("imageinfo", [])
            if not info_list:
                continue
            info = info_list[0]

            mime  = info.get("mime", "")
            if not mime.startswith("image/"):
                continue
            ext = mime.split("/")[-1].lower()
            if ext not in SUPPORTED_FORMATS:
                continue
            width = info.get("width", 0)
            if width < MIN_IMAGE_WIDTH:
                continue

            url = info.get("url", "")
            if not url:
                continue

            extmeta     = info.get("extmetadata", {})
            description = (
                extmeta.get("ImageDescription", {}).get("value", "")
                or extmeta.get("ObjectName", {}).get("value", "")
                or ""
            )
            description = re.sub(r"<[^>]+>", " ", description).strip()
            license_name = extmeta.get("LicenseShortName", {}).get("value", "Unknown")
            artist = re.sub(
                r"<[^>]+>", " ",
                extmeta.get("Artist", {}).get("value", "")
            ).strip()

            results.append({
                "title":       page.get("title", ""),
                "page_id":     page.get("pageid"),
                "url":         url,
                "mime":        mime,
                "width":       width,
                "height":      info.get("height", 0),
                "description": description,
                "license":     license_name,
                "artist":      artist,
                "commons_url": (
                    "https://commons.wikimedia.org/wiki/"
                    + quote(page.get("title", "").replace(" ", "_"))
                ),
            })

    return results


# ---------------------------------------------------------------------------
# Step 1: Download
# ---------------------------------------------------------------------------

def cmd_download(_args) -> None:
    """Crawl Wikimedia Commons categories and download specimen images."""
    for d in (IMAGES_DIR, METADATA_DIR, GROUND_TRUTH_DIR, RESULTS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # Load already-downloaded titles to avoid re-downloading
    seen_titles: set[str] = set()
    for meta_file in METADATA_DIR.glob("*.json"):
        m = _load_json(meta_file)
        if m.get("title"):
            seen_titles.add(m["title"])

    total_existing = len(list(IMAGES_DIR.glob("*.*")))
    total_new      = 0

    logger.info("Existing images: %d  |  Target: %d", total_existing, TARGET_IMAGES)

    for category, label, cat_limit in WIKIMEDIA_CATEGORIES:
        current_total = total_existing + total_new
        if current_total >= TARGET_IMAGES:
            logger.info("Target of %d images reached — stopping.", TARGET_IMAGES)
            break

        remaining = TARGET_IMAGES - current_total
        fetch_limit = min(cat_limit, remaining, 50)

        logger.info("Category: '%s'  (fetching up to %d)", category, fetch_limit)

        # Step A: get file titles from category
        titles = _get_category_file_titles(category, fetch_limit * 3)
        if not titles:
            logger.info("  No files found in category — skipping")
            continue

        # Filter already seen
        new_titles = [t for t in titles if t not in seen_titles]
        if not new_titles:
            logger.info("  All files already downloaded — skipping")
            continue

        # Step B: get imageinfo for these titles
        file_infos = _get_file_info(new_titles[:fetch_limit * 2])
        logger.info("  %d usable images found", len(file_infos))

        downloaded_from_cat = 0

        for info in file_infos:
            if downloaded_from_cat >= fetch_limit:
                break
            if total_existing + total_new >= TARGET_IMAGES:
                break

            title = info["title"]
            if title in seen_titles:
                continue

            safe_name = _safe_filename(title)
            ext       = info["mime"].split("/")[-1].lower()
            if ext == "jpeg":
                ext = "jpg"

            image_path = IMAGES_DIR    / f"{safe_name}.{ext}"
            meta_path  = METADATA_DIR  / f"{safe_name}.json"
            gt_path    = GROUND_TRUTH_DIR / f"{safe_name}.json"

            if image_path.exists():
                seen_titles.add(title)
                continue

            logger.info("  ↓ %s", safe_name[:80])
            ok = _download_binary(info["url"], image_path)
            if not ok:
                continue

            info["local_filename"] = image_path.name
            info["category"]       = category
            info["category_label"] = label
            _save_json(meta_path, info)

            if not gt_path.exists():
                _save_json(gt_path, {f: None for f in STATIC_FIELDS} | {
                    "_verified": False,
                    "_notes":    "",
                })

            seen_titles.add(title)
            total_new            += 1
            downloaded_from_cat  += 1

        logger.info(
            "  Downloaded %d from this category  |  Total so far: %d",
            downloaded_from_cat, total_existing + total_new,
        )

    final_total = len(list(IMAGES_DIR.glob("*.*")))
    logger.info("Done. Total images in dataset: %d", final_total)


# ---------------------------------------------------------------------------
# Step 2: Review
# ---------------------------------------------------------------------------

def cmd_review(_args) -> None:
    """Generate the HTML review file for ground truth entry."""
    image_files = sorted(
        f for f in IMAGES_DIR.iterdir()
        if f.suffix.lower().lstrip(".") in SUPPORTED_FORMATS
    )

    if not image_files:
        logger.error("No images found. Run 'python benchmark.py download' first.")
        sys.exit(1)

    logger.info("Building review page for %d images...", len(image_files))

    cards    = []
    verified = 0

    for img_path in image_files:
        stem = img_path.stem
        meta = _load_json(METADATA_DIR    / f"{stem}.json")
        gt   = _load_json(GROUND_TRUTH_DIR / f"{stem}.json")

        b64  = _image_to_base64(img_path)
        mime = _mime_type(img_path)
        is_v = gt.get("_verified", False)
        if is_v:
            verified += 1

        cards.append({
            "stem":        stem,
            "filename":    img_path.name,
            "data_url":    f"data:{mime};base64,{b64}",
            "description": meta.get("description", ""),
            "license":     meta.get("license", "Unknown"),
            "commons_url": meta.get("commons_url", ""),
            "category":    meta.get("category", ""),
            "width":       meta.get("width", ""),
            "height":      meta.get("height", ""),
            "gt":          gt,
            "verified":    is_v,
        })

    total = len(cards)
    REVIEW_FILE.write_text(
        _render_review_html(cards, total, verified),
        encoding="utf-8",
    )

    logger.info("Review file: %s", REVIEW_FILE.resolve())
    logger.info("Progress   : %d / %d verified", verified, total)
    logger.info("Open in your browser to start reviewing.")


def _render_review_html(cards: list, total: int, verified: int) -> str:
    cards_json = json.dumps(cards, ensure_ascii=False)
    pct = int(verified / total * 100) if total else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ID OCR Benchmark — Ground Truth Review</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f0f2f5;color:#1a1a2e;min-height:100vh}}
header{{background:#1a1a2e;color:#fff;padding:16px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.3)}}
header h1{{font-size:17px;font-weight:600}}
.prog-wrap{{background:rgba(255,255,255,.15);border-radius:20px;height:8px;width:200px}}
.prog-fill{{background:#4ade80;border-radius:20px;height:8px;transition:width .4s}}
.prog-lbl{{font-size:12px;opacity:.8;margin-top:4px;text-align:right}}
.toolbar{{padding:14px 28px;display:flex;gap:10px;align-items:center;background:#fff;border-bottom:1px solid #e2e8f0;flex-wrap:wrap}}
.fbtn{{padding:6px 14px;border-radius:6px;border:1px solid #cbd5e1;background:#fff;cursor:pointer;font-size:13px;color:#475569;transition:all .15s}}
.fbtn:hover{{background:#f1f5f9}}
.fbtn.active{{background:#1a1a2e;color:#fff;border-color:#1a1a2e}}
.prompt-box{{margin-left:auto;background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px 14px;font-size:12px;color:#1e40af;max-width:460px}}
.prompt-box strong{{display:block;margin-bottom:4px}}
.btn-copy{{display:inline-block;margin-top:6px;padding:3px 10px;background:#1e40af;color:#fff;border-radius:4px;cursor:pointer;font-size:11px;border:none}}
main{{padding:20px 28px;display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:20px}}
.card{{background:#fff;border-radius:12px;box-shadow:0 1px 4px rgba(0,0,0,.08);overflow:hidden;border:2px solid transparent;transition:border-color .2s}}
.card.verified{{border-color:#4ade80}}
.card.hidden{{display:none}}
.card-hdr{{padding:10px 14px;background:#f8fafc;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;gap:8px}}
.cidx{{background:#1a1a2e;color:#fff;border-radius:5px;padding:2px 7px;font-size:11px;font-weight:700}}
.cfname{{font-size:12px;font-weight:500;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.vbadge{{background:#dcfce7;color:#166534;font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px}}
.pbadge{{background:#fef9c3;color:#854d0e;font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px}}
.card-img{{padding:10px 14px;text-align:center;background:#f1f5f9}}
.card-img img{{max-width:100%;max-height:240px;object-fit:contain;border-radius:6px;cursor:pointer}}
.card-meta{{padding:5px 14px;font-size:11px;color:#64748b;display:flex;gap:14px;flex-wrap:wrap}}
.card-meta a{{color:#3b82f6;text-decoration:none}}
.card-meta a:hover{{text-decoration:underline}}
.card-body{{padding:12px 14px}}
.instr{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:9px 12px;margin-bottom:12px;font-size:12px;color:#475569;line-height:1.6}}
.instr ol{{padding-left:16px}}
.fgrid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}}
.fg{{display:flex;flex-direction:column;gap:3px}}
.fg.fw{{grid-column:1/-1}}
.fg label{{font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.5px}}
.fg input{{padding:6px 9px;border:1px solid #cbd5e1;border-radius:5px;font-size:12px;color:#1a1a2e;font-family:monospace;transition:border-color .15s}}
.fg input:focus{{outline:none;border-color:#3b82f6;box-shadow:0 0 0 2px rgba(59,130,246,.1)}}
.fg input.filled{{border-color:#4ade80;background:#f0fdf4}}
.paste-area{{width:100%;padding:7px 9px;border:1px dashed #cbd5e1;border-radius:5px;font-size:12px;font-family:monospace;color:#475569;resize:vertical;min-height:70px;background:#fafafa}}
.paste-area:focus{{outline:none;border-color:#3b82f6;border-style:solid}}
.actions{{display:flex;gap:7px;margin-top:8px}}
.btn-parse{{flex:1;padding:7px 0;background:#3b82f6;color:#fff;border:none;border-radius:5px;font-size:12px;font-weight:600;cursor:pointer}}
.btn-parse:hover{{background:#2563eb}}
.btn-save{{flex:1;padding:7px 0;background:#22c55e;color:#fff;border:none;border-radius:5px;font-size:12px;font-weight:600;cursor:pointer}}
.btn-save:hover{{background:#16a34a}}
.btn-clear{{padding:7px 12px;background:#fff;color:#ef4444;border:1px solid #fca5a5;border-radius:5px;font-size:12px;cursor:pointer}}
.btn-clear:hover{{background:#fef2f2}}
.notes-ta{{width:100%;padding:6px 9px;border:1px solid #e2e8f0;border-radius:5px;font-size:12px;color:#475569;resize:vertical;min-height:44px;margin-top:8px;font-family:inherit}}
.smsg{{font-size:12px;padding:5px 9px;border-radius:5px;margin-top:7px;display:none}}
.smsg.ok{{background:#dcfce7;color:#166534;display:block}}
.smsg.err{{background:#fee2e2;color:#991b1b;display:block}}
.lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:1000;align-items:center;justify-content:center}}
.lb.open{{display:flex}}
.lb img{{max-width:90vw;max-height:90vh;border-radius:8px}}
.lb-x{{position:absolute;top:18px;right:22px;color:#fff;font-size:30px;cursor:pointer;opacity:.8}}
.lb-x:hover{{opacity:1}}
</style>
</head>
<body>
<header>
  <h1>🪪 ID OCR Benchmark — Ground Truth Review</h1>
  <div>
    <div class="prog-wrap"><div class="prog-fill" id="pFill" style="width:{pct}%"></div></div>
    <div class="prog-lbl" id="pLbl">{verified} / {total} verified</div>
  </div>
</header>

<div class="toolbar">
  <button class="fbtn active" onclick="setFilter('all',this)">All ({total})</button>
  <button class="fbtn" onclick="setFilter('pending',this)">Pending</button>
  <button class="fbtn" onclick="setFilter('verified',this)">Verified</button>
  <div class="prompt-box">
    <strong>Claude.ai prompt:</strong>
    Extract 5 fields from this identity document. Return ONLY a JSON object with keys:
    document_no, name, issue_date (DD/MM/YYYY), expiry_date (DD/MM/YYYY), address.
    Set missing fields to null. No explanation, no markdown.
    <br><button class="btn-copy" onclick="copyPrompt(this)">Copy prompt</button>
  </div>
</div>

<main id="cards"></main>

<div class="lb" id="lb" onclick="closeLb()">
  <span class="lb-x">&#x2715;</span>
  <img id="lbImg" src="" alt="">
</div>

<script>
const CARDS={cards_json};
const FIELDS=["document_no","name","issue_date","expiry_date","address"];
const PROMPT=`Extract these 5 fields from this identity document and return ONLY a JSON object with exactly these keys: document_no, name, issue_date, expiry_date, address.
Rules:
- Normalise all dates to DD/MM/YYYY format
- Set fields not present on the document to null
- Do NOT extract date of birth as issue_date — issue_date is when the document was issued
- Return ONLY the raw JSON object, no explanation, no markdown, no code fences`;

function copyPrompt(btn){{navigator.clipboard.writeText(PROMPT).then(()=>{{btn.textContent="Copied!";setTimeout(()=>btn.textContent="Copy prompt",1500)}})}}
function setFilter(f,btn){{document.querySelectorAll(".fbtn").forEach(b=>b.classList.remove("active"));btn.classList.add("active");document.querySelectorAll(".card").forEach(c=>{{const v=c.dataset.verified==="true";c.classList.toggle("hidden",f==="verified"?!v:f==="pending"?v:false)}})}}
function parseJSON(s){{
  const ta=document.getElementById("p_"+s);
  let raw=ta.value.trim();
  if(!raw){{showMsg(s,"Paste a JSON response first.","err");return}}
  try{{raw=raw.replace(/^```[\\w]*\\n?/,"").replace(/\\n?```$/,"").trim();const d=JSON.parse(raw);FIELDS.forEach(f=>{{const el=document.getElementById("f_"+s+"_"+f);if(!el)return;const v=d[f]!=null?String(d[f]):"";el.value=v;el.classList.toggle("filled",v.length>0)}});showMsg(s,"Fields populated. Review and save.","ok")}}catch(e){{showMsg(s,"Invalid JSON: "+e.message,"err")}}
}}
function saveGT(s){{
  const gt={{_verified:true,_notes:""}};
  FIELDS.forEach(f=>{{const el=document.getElementById("f_"+s+"_"+f);gt[f]=el&&el.value.trim()||null}});
  const n=document.getElementById("n_"+s);gt._notes=n?n.value.trim():"";
  const blob=new Blob([JSON.stringify(gt,null,2)],{{type:"application/json"}});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=s+".json";a.click();
  const card=document.getElementById("c_"+s);card.dataset.verified="true";card.classList.add("verified");
  document.getElementById("b_"+s).outerHTML=`<span class="vbadge" id="b_${{s}}">✓ Verified</span>`;
  updateProg();showMsg(s,"Saved! Move "+s+".json → benchmark/ground_truth/","ok");
}}
function clearCard(s){{FIELDS.forEach(f=>{{const el=document.getElementById("f_"+s+"_"+f);if(el){{el.value="";el.classList.remove("filled")}}}});const ta=document.getElementById("p_"+s);if(ta)ta.value="";hideMsg(s)}}
function showMsg(s,m,t){{const el=document.getElementById("m_"+s);if(el){{el.textContent=m;el.className="smsg "+t}}}}
function hideMsg(s){{const el=document.getElementById("m_"+s);if(el)el.className="smsg"}}
function updateProg(){{const v=document.querySelectorAll(".card.verified").length,t=document.querySelectorAll(".card").length;document.getElementById("pFill").style.width=(t?Math.round(v/t*100):0)+"%";document.getElementById("pLbl").textContent=v+" / "+t+" verified"}}
function openLb(src){{document.getElementById("lbImg").src=src;document.getElementById("lb").classList.add("open")}}
function closeLb(){{document.getElementById("lb").classList.remove("open")}}

(function render(){{
  const c=document.getElementById("cards");
  CARDS.forEach((card,i)=>{{
    const gt=card.gt||{{}};
    const el=document.createElement("div");
    el.className="card"+(card.verified?" verified":"");
    el.id="c_"+card.stem;
    el.dataset.verified=card.verified?"true":"false";
    el.innerHTML=`
      <div class="card-hdr">
        <span class="cidx">#${{i+1}}</span>
        <span class="cfname" title="${{card.filename}}">${{card.filename}}</span>
        ${{card.verified?`<span class="vbadge" id="b_${{card.stem}}">✓ Verified</span>`:`<span class="pbadge" id="b_${{card.stem}}">Pending</span>`}}
      </div>
      <div class="card-img"><img src="${{card.data_url}}" alt="${{card.filename}}" onclick="openLb(this.src)" title="Click to zoom"></div>
      <div class="card-meta">
        <span>📁 ${{card.category||""}}</span>
        <span>📐 ${{card.width}}×${{card.height}}</span>
        <span>📄 ${{card.license}}</span>
        ${{card.commons_url?`<a href="${{card.commons_url}}" target="_blank">Wikimedia ↗</a>`:""}}
      </div>
      <div class="card-body">
        <div class="instr"><ol>
          <li>Click image to zoom &amp; inspect the document</li>
          <li>Upload to <a href="https://claude.ai" target="_blank">Claude.ai</a> and use the prompt above</li>
          <li>Paste the JSON response below → <strong>Parse JSON</strong></li>
          <li>Review fields, correct errors → <strong>Save</strong></li>
          <li>Move the downloaded <code>.json</code> file to <code>benchmark/ground_truth/</code></li>
        </ol></div>
        <label style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:5px">Paste Claude.ai JSON response</label>
        <textarea class="paste-area" id="p_${{card.stem}}" placeholder='{{"document_no":null,"name":null,"issue_date":null,"expiry_date":null,"address":null}}'></textarea>
        <div class="actions" style="margin-top:7px;margin-bottom:10px">
          <button class="btn-parse" onclick="parseJSON('${{card.stem}}')">⚡ Parse JSON</button>
        </div>
        <div class="fgrid">
          <div class="fg"><label>Document No</label><input type="text" id="f_${{card.stem}}_document_no" value="${{gt.document_no||""}}" placeholder="null" class="${{gt.document_no?"filled":""}}"></div>
          <div class="fg"><label>Name</label><input type="text" id="f_${{card.stem}}_name" value="${{gt.name||""}}" placeholder="null" class="${{gt.name?"filled":""}}"></div>
          <div class="fg"><label>Issue Date (DD/MM/YYYY)</label><input type="text" id="f_${{card.stem}}_issue_date" value="${{gt.issue_date||""}}" placeholder="null" class="${{gt.issue_date?"filled":""}}"></div>
          <div class="fg"><label>Expiry Date (DD/MM/YYYY)</label><input type="text" id="f_${{card.stem}}_expiry_date" value="${{gt.expiry_date||""}}" placeholder="null" class="${{gt.expiry_date?"filled":""}}"></div>
          <div class="fg fw"><label>Address</label><input type="text" id="f_${{card.stem}}_address" value="${{gt.address||""}}" placeholder="null" class="${{gt.address?"filled":""}}"></div>
        </div>
        <textarea class="notes-ta" id="n_${{card.stem}}" placeholder="Optional: doc type, country, issues noticed...">${{gt._notes||""}}</textarea>
        <div class="actions">
          <button class="btn-save" onclick="saveGT('${{card.stem}}')">💾 Save Ground Truth</button>
          <button class="btn-clear" onclick="clearCard('${{card.stem}}')">Clear</button>
        </div>
        <div class="smsg" id="m_${{card.stem}}"></div>
      </div>`;
    c.appendChild(el);
  }});
}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Step 3: Evaluate
# ---------------------------------------------------------------------------

def _normalise(value) -> str | None:
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value).strip().lower())
    return s or None


def _score_field(gt_val, pred_val) -> str:
    gt, pred = _normalise(gt_val), _normalise(pred_val)
    if gt is None and pred is None: return "true_null"
    if gt is None:                   return "false_positive"
    if pred is None:                 return "false_null"
    if gt == pred:                   return "correct"
    return "wrong_value"


def _run_extractor(image_path: Path) -> dict:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from scripts.extractor import extract
        from scripts.converter import DocumentFormat
        ext        = image_path.suffix.lower().lstrip(".")
        bedrock_fmt = "jpeg" if ext in ("jpg", "jpeg") else ext
        result     = extract(image_path.read_bytes(), DocumentFormat.IMAGE, bedrock_fmt)
        return {f: getattr(result, f, None) for f in STATIC_FIELDS}
    except ImportError:
        logger.warning("Extractor not importable — using null stub for %s", image_path.name)
        return {f: None for f in STATIC_FIELDS}
    except Exception as exc:
        logger.error("Extractor error on %s: %s", image_path.name, exc)
        return {f: None for f in STATIC_FIELDS}


def cmd_evaluate(_args) -> None:
    gt_files = [
        f for f in sorted(GROUND_TRUTH_DIR.glob("*.json"))
        if _load_json(f).get("_verified", False)
    ]

    if not gt_files:
        logger.error("No verified ground truth files. Complete Step 2 first.")
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Evaluating %d verified documents...", len(gt_files))

    doc_results  = []
    field_counts = {
        f: {"correct": 0, "true_null": 0, "false_positive": 0,
            "false_null": 0, "wrong_value": 0}
        for f in STATIC_FIELDS
    }

    for gt_file in gt_files:
        stem       = gt_file.stem
        gt         = _load_json(gt_file)
        meta       = _load_json(METADATA_DIR / f"{stem}.json")
        image_path = next(
            (IMAGES_DIR / f"{stem}.{ext}" for ext in SUPPORTED_FORMATS | {"jpeg"}
             if (IMAGES_DIR / f"{stem}.{ext}").exists()),
            None,
        )
        if image_path is None:
            logger.warning("Image not found for %s — skipping", stem)
            continue

        logger.info("  → %s", image_path.name)
        predicted = _run_extractor(image_path)
        _save_json(RESULTS_DIR / f"{stem}.json", predicted)

        field_scores = {}
        for field in STATIC_FIELDS:
            outcome = _score_field(gt.get(field), predicted.get(field))
            field_scores[field] = {
                "outcome":      outcome,
                "ground_truth": gt.get(field),
                "predicted":    predicted.get(field),
            }
            field_counts[field][outcome] += 1

        non_null = [f for f in STATIC_FIELDS if gt.get(f) is not None]
        doc_correct = all(
            field_scores[f]["outcome"] == "correct" for f in non_null
        ) if non_null else True

        doc_results.append({
            "stem":        stem,
            "filename":    image_path.name,
            "category":    meta.get("category", ""),
            "country":     meta.get("category_label", ""),
            "commons_url": meta.get("commons_url", ""),
            "notes":       gt.get("_notes", ""),
            "doc_correct": doc_correct,
            "field_scores": field_scores,
        })

    n = len(doc_results)
    if n == 0:
        logger.error("No documents evaluated — no matching image files found for verified ground truth.")
        sys.exit(1)

    field_accuracy = {}
    for field in STATIC_FIELDS:
        c = field_counts[field]
        total   = sum(c.values())
        correct = c["correct"] + c["true_null"]
        field_accuracy[field] = {
            "accuracy":       round(correct / total, 4) if total else None,
            "correct":        c["correct"],
            "true_null":      c["true_null"],
            "false_positive": c["false_positive"],
            "false_null":     c["false_null"],
            "wrong_value":    c["wrong_value"],
            "total":          total,
        }

    docs_correct  = sum(1 for d in doc_results if d["doc_correct"])
    doc_accuracy  = round(docs_correct / n, 4) if n else None
    field_accs    = [v["accuracy"] for v in field_accuracy.values() if v["accuracy"] is not None]
    mean_field_acc = round(sum(field_accs) / len(field_accs), 4) if field_accs else None

    report = {
        "summary": {
            "total_documents":     n,
            "documents_correct":   docs_correct,
            "document_accuracy":   doc_accuracy,
            "mean_field_accuracy": mean_field_acc,
        },
        "per_field":    field_accuracy,
        "per_document": doc_results,
    }
    _save_json(REPORT_FILE, report)

    print("\n" + "=" * 62)
    print("  BENCHMARK REPORT")
    print("=" * 62)
    print(f"  Documents evaluated : {n}")
    print(f"  Document accuracy   : {doc_accuracy*100:.1f}%  ({docs_correct}/{n} fully correct)")
    print(f"  Mean field accuracy : {mean_field_acc*100:.1f}%")
    print()
    print(f"  {'Field':<20} {'Accuracy':>9}  {'Correct':>7}  {'FP':>6}  {'FN':>6}  {'Wrong':>7}")
    print("  " + "-" * 62)
    for f in STATIC_FIELDS:
        fa  = field_accuracy[f]
        acc = f"{fa['accuracy']*100:.1f}%" if fa["accuracy"] is not None else "N/A"
        print(f"  {f:<20} {acc:>9}  {fa['correct']:>7}  "
              f"{fa['false_positive']:>6}  {fa['false_null']:>6}  {fa['wrong_value']:>7}")
    print("=" * 62)
    print(f"\n  Full report → {REPORT_FILE.resolve()}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Government ID OCR benchmark builder and evaluator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command")
    sub.add_parser("download", help="Step 1: Download images from Wikimedia Commons")
    sub.add_parser("review",   help="Step 2: Generate HTML review file")
    sub.add_parser("evaluate", help="Step 3: Run extractor and evaluate")
    sub.add_parser("all",      help="Run all three steps")

    args = p.parse_args()
    if   args.command == "download":  cmd_download(args)
    elif args.command == "review":    cmd_review(args)
    elif args.command == "evaluate":  cmd_evaluate(args)
    elif args.command == "all":
        cmd_download(args); cmd_review(args); cmd_evaluate(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()

