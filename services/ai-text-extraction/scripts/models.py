"""
models.py
---------
Pydantic models that define the shape of data flowing through the module.

  ExtractionResult  — the five-field response contract returned to the caller

Nothing here knows about Bedrock, files, or conversion logic.
These are pure data contracts.
"""

import re
from typing import Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------

class ExtractionResult(BaseModel):
    """
    The fixed response shape returned to the caller for every extraction attempt.

    All five fields are always present. Fields the model cannot find are null.

    Fields:
        document_no  — Passport/licence/ID number. Null if not found.
        name         — Full name as printed on the document.
        issue_date   — Normalised to YYYY-MM-DD. Null if not found.
        expiry_date  — Normalised to YYYY-MM-DD. Null if not found.
        address      — Full address as printed. Null if not found.
    """

    document_no:  Optional[str] = None
    name:         Optional[str] = None
    issue_date:   Optional[str] = None
    expiry_date:  Optional[str] = None
    address:      Optional[str] = None

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("issue_date", "expiry_date", mode="before")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        """
        Ensure dates conform to YYYY-MM-DD.
        Accepts None — returns None unchanged.
        Raises ValueError if a non-null value does not match the pattern.
        """
        if v is None:
            return None
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v).strip()):
            raise ValueError(
                f"Date '{v}' does not match required format YYYY-MM-DD. "
                "The extractor must normalise dates before constructing this model."
            )
        return v.strip()

    @field_validator("document_no", "name", "address", mode="before")
    @classmethod
    def strip_strings(cls, v: Optional[str]) -> Optional[str]:
        """Strip whitespace from string fields. Treat empty strings as null."""
        if v is None:
            return None
        stripped = str(v).strip()
        return stripped if stripped else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_api_response(self) -> dict:
        """Serialise to the 5-field JSON response contract."""
        return {
            "document_no": self.document_no,
            "name":        self.name,
            "issue_date":  self.issue_date,
            "expiry_date": self.expiry_date,
            "address":     self.address,
        }

    def missing_fields(self) -> list[str]:
        """Return names of the 5 fields that are still null. Used for internal logging."""
        return [
            f for f in ("document_no", "name", "issue_date", "expiry_date", "address")
            if getattr(self, f) is None
        ]
