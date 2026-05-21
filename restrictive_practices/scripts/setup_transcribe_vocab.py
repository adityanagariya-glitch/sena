"""One-time script: create NDIS custom vocabulary in Amazon Transcribe.

Run once per AWS account/region to improve recognition of NDIS domain terms.
After running, set SENA_AI_TRANSCRIPTION_VOCAB_NAME=sena-ndis-vocab in .env.

Usage:
    conda activate sena_env
    python scripts/setup_transcribe_vocab.py [--delete]

Options:
    --delete    Delete the vocabulary instead of creating it
"""

import argparse
import sys
import time

import boto3

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from config import settings  # noqa: E402

VOCAB_NAME = "sena-ndis-vocab"

# NDIS-specific phrases that Transcribe often mishears
PHRASES = [
    "NDIS",
    "BSP",
    "behaviour support plan",
    "restrictive practice",
    "physical restraint",
    "chemical restraint",
    "mechanical restraint",
    "seclusion",
    "environmental restraint",
    "debriefing",
    "debrief",
    "NDIS Quality and Safeguards Commission",
    "support worker",
    "support coordinator",
    "participant",
    "PBSP",
    "positive behaviour support",
]


def _make_client() -> "boto3.client":
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("transcribe", **kwargs)


def create_vocab() -> None:
    tc = _make_client()
    print(f"Creating vocabulary '{VOCAB_NAME}' in {settings.aws_region}...")
    tc.create_vocabulary(
        VocabularyName=VOCAB_NAME,
        LanguageCode=settings.transcription_language,
        Phrases=PHRASES,
    )
    print("Waiting for vocabulary to become READY...")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        resp = tc.get_vocabulary(VocabularyName=VOCAB_NAME)
        state = resp["VocabularyState"]
        print(f"  state: {state}")
        if state == "READY":
            print(f"\nVocabulary ready. Add to .env:\n  SENA_AI_TRANSCRIPTION_VOCAB_NAME={VOCAB_NAME}")
            return
        if state == "FAILED":
            print(f"FAILED: {resp.get('FailureReason')}")
            sys.exit(1)
        time.sleep(5)
    print("Timed out waiting for vocabulary.")
    sys.exit(1)


def delete_vocab() -> None:
    tc = _make_client()
    print(f"Deleting vocabulary '{VOCAB_NAME}'...")
    tc.delete_vocabulary(VocabularyName=VOCAB_NAME)
    print("Deleted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage NDIS custom Transcribe vocabulary")
    parser.add_argument("--delete", action="store_true", help="Delete the vocabulary")
    args = parser.parse_args()

    if args.delete:
        delete_vocab()
    else:
        create_vocab()
