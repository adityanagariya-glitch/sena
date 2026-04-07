from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TranscribeTurn:
    text: str
    confidence: float


class TranscribeService:
    async def normalize_turn(self, transcript: str, confidence: float) -> TranscribeTurn:
        cleaned = " ".join(transcript.split())
        return TranscribeTurn(text=cleaned, confidence=confidence)
