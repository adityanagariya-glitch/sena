import boto3
import json
import os
from markitdown import MarkItDown

from config import REGION, BUCKET_NAME, ORG_PREFIX, MD_PREFIX

s3 = boto3.client("s3", region_name=REGION)
md_converter = MarkItDown()

LOCAL_FOLDER = r"C:\Users\BAPS\Documents\SENA_RAG\policies"

SUPPORTED_EXTENSIONS = {
    ".pdf", ".txt", ".md",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".csv", ".html", ".htm"
}

uploaded_raw = []
uploaded_md  = []
skipped      = []

# Expects LOCAL_FOLDER/{org_id}/filename.pdf structure
for org_id in os.listdir(LOCAL_FOLDER):
    org_path = os.path.join(LOCAL_FOLDER, org_id)
    if not os.path.isdir(org_path):
        continue

    for filename in os.listdir(org_path):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            skipped.append(filename)
            print(f"Skipped:  {filename} (unsupported format)")
            continue

        filepath = os.path.join(org_path, filename)
        raw_key  = f"{ORG_PREFIX}{org_id}/{filename}"

        # Upload raw file
        s3.upload_file(filepath, BUCKET_NAME, raw_key)
        uploaded_raw.append(raw_key)
        print(f"Uploaded raw:  {raw_key}")

        # Convert to .md and upload to md prefix
        base_name = os.path.splitext(filename)[0]
        md_key    = f"{MD_PREFIX}{org_id}/{base_name}.md"

        try:
            result   = md_converter.convert(filepath)
            md_bytes = result.text_content.encode("utf-8")
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=md_key,
                Body=md_bytes,
                ContentType="text/markdown"
            )
            # Metadata sidecar — same pattern as Lambda trigger_ingestion
            sidecar = json.dumps({
                "metadataAttributes": {
                    "org_id":   org_id,
                    "doc_type": "policy"
                }
            })
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=f"{md_key}.metadata.json",
                Body=sidecar.encode("utf-8"),
                ContentType="application/json"
            )
            uploaded_md.append(md_key)
            print(f"Converted & uploaded: {filename} → {md_key} + sidecar")
        except Exception as e:
            skipped.append(filename)
            print(f"Conversion failed: {filename} — {e}")

print(f"\nDone! {len(uploaded_raw)} raw | {len(uploaded_md)} .md | {len(skipped)} skipped")
