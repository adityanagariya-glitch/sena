"""Bedrock Guardrails helpers — input/output scanning + persistence scrubbing."""
from config import bedrock_runtime, GUARDRAILS


def _last_user_text(messages):
    """Pull most-recent user message text for input guardrails."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            for part in msg.get("content", []) or []:
                if isinstance(part, dict) and part.get("text"):
                    return part["text"]
    return ""


def _apply_guardrail(gid, version, text, source):
    """Run a single guardrail via apply_guardrail. Returns block message or None if passed."""
    if not text:
        return None
    try:
        resp = bedrock_runtime.apply_guardrail(
            guardrailIdentifier=gid,
            guardrailVersion=version,
            source=source,  # "INPUT" or "OUTPUT"
            content=[{"text": {"text": text}}],
        )
        if resp.get("action") == "GUARDRAIL_INTERVENED":
            outputs = resp.get("outputs") or []
            if outputs and outputs[0].get("text"):
                return outputs[0]["text"]
            return "Sorry, I can't help with that."
        return None
    except Exception as e:
        print(f"[bedrock-guardrails] apply_guardrail({gid}, {source}) error: {e}")
        return None


def _scrub_for_persistence(text):
    """Run text through the primary Guardrail (OUTPUT) before storing.

    If the guardrail anonymises/redacts, store the redacted version. Raw
    un-redacted text is never persisted. Falls through to raw if no
    guardrail is configured.
    """
    if not text or not GUARDRAILS:
        return text
    gid, ver = GUARDRAILS[0]
    redacted = _apply_guardrail(gid, ver, text, "OUTPUT")
    return redacted if redacted else text
