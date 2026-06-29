"""Shared Langfuse client helper — imported by all SENA services.

Responsibilities:
  - Load root .env once so LANGFUSE_* keys land in os.environ before
    get_client() reads them (dev-local pattern; in prod the vars are
    set at the system level and load_dotenv is a no-op).
  - Expose get_client() as a single canonical import path.
  - Provide a service-tagged update helper so every service attaches
    metadata={"service": <name>} to spans/generations consistently.

Usage in each service's LLM module:

    from sena_common.langfuse_helper import get_client, SERVICE_TAG

    langfuse = get_client()
    SERVICE = "my_service"          # folder name

    @observe(as_type="generation", name="my-op", capture_input=False, capture_output=False)
    def my_llm_call(...):
        response = bedrock.converse(...)
        langfuse.update_current_generation(
            model=MODEL_ID,
            input=prompt,
            output=text,
            usage_details={"input": in_tok, "output": out_tok},
            metadata=SERVICE_TAG(SERVICE),
        )
"""

from pathlib import Path

# ── .env loading (dev only) ───────────────────────────────────────────────────
# find_dotenv() walks up from cwd until it finds a .env file; load_dotenv()
# then sets any unset os.environ keys. In production the vars are already in
# the environment, so this is a no-op.
try:
    from dotenv import find_dotenv, load_dotenv
    _env = find_dotenv(usecwd=True)
    if _env:
        load_dotenv(_env, override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on system env vars

# ── Langfuse client (auto-disabled if keys not set) ──────────────────────────
from langfuse import get_client  # re-export for convenience


def SERVICE_TAG(service_name: str) -> dict:
    """Return a metadata dict that tags any span/generation with the service name.

    Use as:
        langfuse.update_current_generation(metadata=SERVICE_TAG("ai_chatbot"), ...)
        langfuse.update_current_span(metadata=SERVICE_TAG("voice"), ...)
    """
    return {"service": service_name}
