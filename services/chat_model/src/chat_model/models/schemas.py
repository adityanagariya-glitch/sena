from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    session_id: str | None = Field(
        default=None,
        description="Conversation session ID. Auto-generated if not provided.",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="User message (1-4000 characters)",
    )

    @field_validator("message")
    @classmethod
    def validate_message_not_blank(cls, v: str) -> str:
        if not v or v.isspace():
            raise ValueError("Message cannot be empty or whitespace")
        return v.strip()


class ChatResponse(BaseModel):
    session_id: str = Field(..., description="Conversation session ID")
    response: str = Field(..., description="AI-generated response")
    conversation: list[Message] = Field(..., description="Full conversation history")


class SessionRead(BaseModel):
    session_id: str = Field(..., description="Conversation session ID")
    conversation: list[Message] = Field(..., description="Conversation messages")


class SessionClearResponse(BaseModel):
    message: str = Field(..., description="Confirmation message")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service health status")
    model: str = Field(..., description="Active LLM model")
