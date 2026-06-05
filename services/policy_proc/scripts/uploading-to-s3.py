import boto3
import os

from config import REGION, BUCKET_NAME

s3 = boto3.client("s3", region_name=REGION)

LOCAL_FOLDER = r"C:\Users\BAPS\Documents\SENA_RAG\policies"  

# All formats supported by Bedrock KB
SUPPORTED_EXTENSIONS = {
    ".pdf", ".txt", ".md",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".csv", ".html", ".htm"
}

uploaded = []
skipped  = []

for filename in os.listdir(LOCAL_FOLDER):
    ext = os.path.splitext(filename)[1].lower()
    if ext in SUPPORTED_EXTENSIONS:
        filepath = os.path.join(LOCAL_FOLDER, filename)
        s3.upload_file(filepath, BUCKET_NAME, filename)
        uploaded.append(filename)
        print(f"Uploaded: {filename}")
    else:
        skipped.append(filename)
        print(f"Skipped:  {filename} (unsupported format)")

print(f"\nDone! {len(uploaded)} uploaded, {len(skipped)} skipped.")
