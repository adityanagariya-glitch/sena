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

# Spoken-number words are PROTECTED from repeat-collapse: "five five five" is a
# phone-digit run (5-5-5) and "oh oh oh" is 0-0-0 (e.g. 000) — collapsing those
# would corrupt personal/phone data.
_NUMBER_WORDS = frozenset({
    "oh", "o", "zero", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "double", "triple",
})
# 3+ consecutive identical words (space/comma separated) are disfluency or
# emphasis — "ok ok ok" -> "ok". Threshold is 3 ON PURPOSE: valid English
# doubles ("had had", "that that", "bye bye", "no-no", "so so") must survive.
_REPEAT_RE = re.compile(r"\b(\w+)\b(?:[\s,]+\1\b){2,}", re.IGNORECASE)


def _collapse_repeat(m: "re.Match[str]") -> str:
    token = m.group(1)
    # Protect both spelled-out number words ("five five five") AND numeral
    # digits ("5 5 5") — ASR engines (incl. AWS Transcribe) often render
    # spoken phone/ID numbers as numerals rather than words.
    if token.lower() in _NUMBER_WORDS or token.isdigit():
        return m.group(0)  # keep run intact (phone digits, 000/999, etc.)
    return token            # 3+ repeats -> single occurrence


def strip_fillers(text: str) -> str:
    """Clean an ASR transcript (meaning-preserving): drop vocalized fillers and
    collapse 3+ identical-word repeats. Spoken-number runs are protected."""
    cleaned = _FILLER_RE.sub("", text)
    cleaned = _REPEAT_RE.sub(_collapse_repeat, cleaned)  # "ok ok ok" -> "ok" (numbers exempt)
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
        # Whitespace-only here — this becomes the permanent record (DB
        # transcript/case-note field, session history). strip_fillers() is
        # applied separately, only to the copy sent to the model, in the
        # prompt builders. A participant's actual speech pattern — including
        # repetition from stuttering, echolalia, or palilalia — is not noise
        # to be "corrected"; it must survive in the stored record unaltered.
        cleaned = " ".join(transcript.split())
        return TranscribeTurn(text=cleaned, confidence=confidence)
