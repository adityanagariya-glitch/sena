from pydantic import BaseModel, Field, model_validator
from typing import Annotated


def _get_limits():
    """Lazy import to avoid circular dependency with config."""
    from config import get_settings
    s = get_settings()
    return s.min_summaries, s.max_summaries, s.min_summary_length, s.max_summary_length


class SummarizeRequest(BaseModel):
    summaries: list[str] = Field(
        ...,
        description="List of text summaries to consolidate.",
        examples=[["Summary one.", "Summary two.", "Summary three."]],
    )

    @model_validator(mode="after")
    def validate_summaries(self) -> "SummarizeRequest":
        min_s, max_s, min_len, max_len = _get_limits()

        if not (min_s <= len(self.summaries) <= max_s):
            raise ValueError(
                f"Number of summaries must be between {min_s} and {max_s}. "
                f"Got {len(self.summaries)}."
            )

        for i, summary in enumerate(self.summaries):
            stripped = summary.strip()
            if not stripped:
                raise ValueError(f"Summary at index {i} is empty or whitespace.")
            if not (min_len <= len(stripped) <= max_len):
                raise ValueError(
                    f"Summary at index {i} must be between {min_len} and {max_len} "
                    f"characters. Got {len(stripped)}."
                )

        return self


class TokenUsage(BaseModel):
    input_tokens: int = Field(..., description="Number of input tokens consumed.")
    output_tokens: int = Field(..., description="Number of output tokens generated.")
    total_tokens: int = Field(..., description="Total tokens (input + output).")


class SummarizeResponse(BaseModel):
    consolidated_summary: str = Field(
        ...,
        description="The consolidated summary produced by the model.",
    )
    token_usage: TokenUsage = Field(
        ...,
        description="Token usage for this request.",
    )


class ErrorResponse(BaseModel):
    detail: str
