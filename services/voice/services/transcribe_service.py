from __future__ import annotations

import re
from dataclasses import dataclass

# Vocalized hesitation sounds only — "um / uh / er / erm / err" and their
# elongations ("ummm", "uhh"). These are never lexical content in English, so
# removing them cannot change clinical meaning. Deliberately NOT stripping
# "ah / oh / hmm / mm / like / you know / well / so" — in a support-work record
# those can carry meaning or nuance, and this must stay meaning-lossless.
# NOTE: kept byte-identical with case_review's run_transcription filler strip;
# the two services are intentionally isolated (no shared import path), so this
# small pure helper is duplicated rather than shared.
_FILLER_RE = re.compile(r"\b(?:um+|uh+|erm+|err+|er+)\b", re.IGNORECASE)


def strip_fillers(text: str) -> str:
    """Remove vocalized filler sounds from an ASR transcript (meaning-preserving)."""
    cleaned = _FILLER_RE.sub("", text)
    cleaned = re.sub(r",(?:\s*,)+", ",", cleaned)       # collapse commas orphaned by removal
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)  # drop space before punctuation
    cleaned = re.sub(r",\s*([.!?])", r"\1", cleaned)    # drop comma stranded before sentence end
    cleaned = re.sub(r"\s{2,}", " ", cleaned)           # collapse runs of whitespace
    cleaned = re.sub(r"^[\s,]+", "", cleaned)           # trim leading space/comma
    return cleaned.strip()


@dataclass
class TranscribeTurn:
    text: str
    confidence: float


class TranscribeService:
    async def normalize_turn(self, transcript: str, confidence: float) -> TranscribeTurn:
        cleaned = " ".join(transcript.split())
        cleaned = strip_fillers(cleaned)
        return TranscribeTurn(text=cleaned, confidence=confidence)
