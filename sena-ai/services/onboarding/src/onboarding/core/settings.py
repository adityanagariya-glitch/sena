from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class OnboardingSettings(BaseSettings):
    """
    All env vars read as SENA_AI_<FIELD_NAME_UPPER>.
    No Field(alias=...) — aliases bypass env_prefix in pydantic-settings.
    """

    # env_file list: checked in order, later entries override earlier.
    # "../../.env" = sena-ai/.env (shared across services) when cwd = sena-ai/services/onboarding
    # ".env" = local override if present
    model_config = SettingsConfigDict(
        env_file=["../../.env", ".env"],
        env_prefix="SENA_AI_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service ───────────────────────────────────────────────────────────────
    # SENA_AI_SERVICE_VERSION
    service_version: str = "0.1.0"
    # SENA_AI_ENVIRONMENT
    environment: str = "development"
    # SENA_AI_DEBUG
    debug: bool = True
    # SENA_AI_HOST
    host: str = "0.0.0.0"
    # SENA_AI_ONBOARDING_PORT
    onboarding_port: int = 8083
    # SENA_AI_LOG_LEVEL
    log_level: str = "INFO"

    # ── Redis ─────────────────────────────────────────────────────────────────
    # SENA_AI_REDIS_URL
    redis_url: str = "redis://localhost:6379"
    # SENA_AI_ONBOARDING_SESSION_TTL_MIN — inactivity timeout, extended each WS message
    onboarding_session_ttl_min: int = 15
    # SENA_AI_ONBOARDING_SESSION_MAX_MIN — hard session cap
    onboarding_session_max_min: int = 60
    # SENA_AI_ONBOARDING_RESUMPTION_TTL_MIN — how long a resumption handle stays valid
    onboarding_resumption_ttl_min: int = 30

    # ── Gemini ────────────────────────────────────────────────────────────────
    # SENA_AI_GEMINI_API_KEY
    gemini_api_key: str = ""
    # SENA_AI_GEMINI_LIVE_MODEL_ID
    gemini_live_model_id: str = "gemini-3.1-flash-live-preview"

    # ── App backend webhook ───────────────────────────────────────────────────
    # SENA_AI_APP_WEBHOOK_URL
    app_webhook_url: str = "https://mock.example.com/webhooks/sena"
    # SENA_AI_APP_WEBHOOK_SECRET
    app_webhook_secret: str = ""
    # SENA_AI_ONBOARDING_WEBHOOK_MAX_RETRIES
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
    # See .claude/plans/per-screen-session-model/ISSUE_AND_SOLUTION.md.
    onboarding_tool_state_channel: bool = True
    # SENA_AI_ONBOARDING_FRAME_FPS_LIMIT
    onboarding_frame_fps_limit: int = 2
    # SENA_AI_ONBOARDING_SILENCE_TIMEOUT_SEC — seconds of user silence before
    # Gemini is prompted to check in ("are you still there?"). 0 = disabled.
    onboarding_silence_timeout_sec: int = 8
    # SENA_AI_VOICE_COVERAGE_ENFORCED — reject field_apply for out-of-coverage fields
    voice_coverage_enforced: bool = True
    # SENA_AI_ONBOARDING_VOICE_VALIDATION_ADVISORY — when True the voice path
    # emits advisory warnings instead of blocking on field validation failures.
    # Strict rejection still fires for None/empty/un-parseable values.
    # Operator rollback: set SENA_AI_ONBOARDING_VOICE_VALIDATION_ADVISORY=false.
    onboarding_voice_validation_advisory: bool = True
    # SENA_AI_FIELD_APPLY_LOG_LEVEL
    field_apply_log_level: str = "DEBUG"

    # ── Screen state injection (Phase D-replacement) ──────────────────────────
    # SENA_AI_SCREEN_STATE_MAX_BYTES — hard cap on screen_state payload size
    screen_state_max_bytes: int = 8192

    # ── Session resumption (Phase E) ──────────────────────────────────────────
    # SENA_AI_RESUMPTION_HANDLE_TTL_SEC — handle expiry (default 10 min)
    resumption_handle_ttl_sec: int = 600
    # SENA_AI_RESUMPTION_REPLAY_TURNS — transcript turns replayed on resume
    resumption_replay_turns: int = 4

    # ── Derived (seconds) ─────────────────────────────────────────────────────
    @property
    def session_ttl_sec(self) -> int:
        return self.onboarding_session_ttl_min * 60

    @property
    def session_max_sec(self) -> int:
        return self.onboarding_session_max_min * 60

    @property
    def resumption_ttl_sec(self) -> int:
        return self.onboarding_resumption_ttl_min * 60


settings = OnboardingSettings()
