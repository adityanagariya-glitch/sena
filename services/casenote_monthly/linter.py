"""Language linter: SBLC (strengths-based) + TILA (trauma-informed) enforcement."""
import re

_SBLC_MAP = {
    "cannot": "is building skills to",
    "refuses": "experiences difficulty with",
    "fails": "is developing competence in",
    "unable to": "is working toward being able to",
    "doesn't": "is building competence in",
    "non-compliant": "declining participation in",
}

_TILA_MAP = {
    "manipulative": "expressing unmet needs",
    "attention-seeking": "connection-seeking",
    "defiant": "asserting autonomy",
    "non-compliant": "declining participation",
    "aggressive": "expressing distress",
    "hostile": "expressing strong emotion",
}


def lint(text: str) -> tuple[str, list[str]]:
    """Apply SBLC + TILA lexicon replacements.

    Returns: (cleaned_text, list_of_violations_found)
    """
    violations = []
    result = text

    # SBLC pass
    for deficit_word, replacement in _SBLC_MAP.items():
        pattern = r"\b" + re.escape(deficit_word) + r"\b"
        matches = re.findall(pattern, result, re.IGNORECASE)
        if matches:
            violations.extend([f"SBLC: '{m}'" for m in matches])
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # TILA pass
    for stigma_word, replacement in _TILA_MAP.items():
        pattern = r"\b" + re.escape(stigma_word) + r"\b"
        matches = re.findall(pattern, result, re.IGNORECASE)
        if matches:
            violations.extend([f"TILA: '{m}'" for m in matches])
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result, violations
