from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class OnboardingSettings(BaseSettings):
    """
    All env vars read as SENA_AI_<FIELD_NAME_UPPER>.
    No Field(alias=...) — aliases bypass env_prefix in pydantic-settings.
    """

    # env_file list: checked in order, later entries override earlier.
    # "../../.env" = repo-root .env (shared across services) when cwd = services/onboarding
    # ".env" = local override if present
    model_config = SettingsConfigDict(
        env_file=["../../.env", ".env"],
        env_prefix="SENA_AI_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service ───────────────────────────────────────────────────────────────
    service_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    onboarding_port: int = 8083
    log_level: str = "INFO"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"
    # SENA_AI_ONBOARDING_SESSION_MAX_MIN — hard session cap (feeds session_max_sec)
    onboarding_session_max_min: int = 60

    # ── Gemini ────────────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_live_model_id: str = "gemini-3.1-flash-live-preview"

    # ── App backend webhook ───────────────────────────────────────────────────
    app_webhook_url: str = "https://mock.example.com/webhooks/sena"
    app_webhook_secret: str = ""
    onboarding_webhook_max_retries: int = 3

    # ── Feature flags ─────────────────────────────────────────────────────────
    # SENA_AI_ONBOARDING_GROUNDING_ENABLED — default off until compliance sign-off
    onboarding_grounding_enabled: bool = False
    # SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED — default ON.
    # Controls whether prior-step summaries are persisted into and rendered
    # out of the per-(tenant_id, participant_id) Redis bucket. Bucket key is
    # `sena:onboarding:user_ctx:{tenant_id}:{participant_id}` so isolation is
    # structural (no cross-tenant read possible by construction). When OFF
    # the agent has no memory of prior screens — symptom: re-asks for the
    # participant's name on every step. Single-flag rollback path.
    onboarding_cross_screen_context_enabled: bool = True
    # SENA_AI_ONBOARDING_TOOL_STATE_CHANNEL — Option D state-channel flag.
    # When True (default), prompt_builder shrinks bootstrap to header-only;
    # Flutter must include fresh TurnPayload `state` in every tool_response.
    onboarding_tool_state_channel: bool = True
    # SENA_AI_ONBOARDING_SILENCE_TIMEOUT_SEC — seconds of user silence before
    # Gemini is prompted to check in ("are you still there?"). 0 = disabled.
    onboarding_silence_timeout_sec: int = 8
    # SENA_AI_ONBOARDING_MOBILE_BRIDGE_TIMEOUT_SEC — how long the backend waits
    # for the Flutter client to answer a tool_request before returning a
    # mobile_timeout rejection. 12s default (5s caused false timeouts).
    onboarding_mobile_bridge_timeout_sec: float = 12.0

    # ── Auth ─────────────────────────────────────────────────────────────────
    # SENA_AI_JWT_ENABLED: true (prod, require JWT) or false (dev, accept dev_header)
    jwt_enabled: bool = False
    # RS256 public key PEM for JWT verification (required when jwt_enabled=true)
    jwt_public_key_pem: str | None = None
    jwt_issuer: str | None = None
    jwt_audience: str | None = None

    # ── Screen state injection ────────────────────────────────────────────────
    # SENA_AI_SCREEN_STATE_MAX_BYTES — hard cap on screen_state payload size
    screen_state_max_bytes: int = 8192

    # ── Session resumption ────────────────────────────────────────────────────
    # SENA_AI_RESUMPTION_HANDLE_TTL_SEC — handle expiry (default 10 min)
    resumption_handle_ttl_sec: int = 600
    # SENA_AI_RESUMPTION_REPLAY_TURNS — transcript turns replayed on resume
    resumption_replay_turns: int = 4

    # ── Derived (seconds) ─────────────────────────────────────────────────────
    @property
    def session_max_sec(self) -> int:
        return self.onboarding_session_max_min * 60


settings = OnboardingSettings()