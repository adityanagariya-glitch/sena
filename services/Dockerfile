# Unified multi-stage Dockerfile for all SENA AI services.
#
# Build context must be the repo root (parent of services/):
#   docker compose -f services/docker-compose.deploy.yml up --build
#
# Build a single stage manually:
#   docker build --target voice -t sena-voice .
#   docker build --target onboarding -t sena-onboarding .
#   docker build --target case-review -t sena-case-review .
#   docker build --target ai-chatbot -t sena-ai-chatbot .

# ── Base: shared Python env + sena-common ─────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install -U pip

COPY shared /app/shared
RUN pip install /app/shared


# ── Voice — case note dictation via Bedrock (port 8000) ───────────────────
FROM base AS voice

COPY services/voice/pyproject.toml /app/pyproject.toml
RUN pip install .

COPY services/voice/src /app/src
ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "voice.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]


# ── Onboarding — Gemini Live voice onboarding (port 8001) ─────────────────
FROM base AS onboarding

COPY services/onboarding/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/onboarding/src /app/src
ENV PYTHONPATH=/app/src

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health/live').status==200 else 1)"

CMD ["uvicorn", "onboarding.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]


# ── Case Review — pgvector intelligence layer (port 8002) ─────────────────
FROM base AS case-review

COPY services/case_review/pyproject.toml /app/pyproject.toml
COPY services/case_review/src /app/src
RUN pip install .

ENV PYTHONPATH=/app/src

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health/live').status==200 else 1)"

CMD ["uvicorn", "case_review.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8002"]


# ── AI Chatbot — gateway + staff API + policy API (port 8003) ─────────────
#
# The gateway spawns staff_api and policy_api as child processes bound to
# 127.0.0.1, so all three must live in the same container.
FROM base AS ai-chatbot

# Gateway deps (fastapi, uvicorn, httpx, websockets, jinja2)
COPY services/ai_chatbot/requirements.txt /tmp/req-gateway.txt
RUN pip install -r /tmp/req-gateway.txt

# Staff + policy child deps (boto3 for Bedrock, PyJWT for auth)
RUN pip install boto3 PyJWT

# Copy all code the gateway manages
COPY services/ai_chatbot  /app/services/ai_chatbot
COPY services/staff       /app/services/staff
COPY services/policy_proc /app/services/policy_proc

# Repo root on PYTHONPATH so `services.policy_proc.scripts.*` imports resolve
ENV PYTHONPATH=/app

# Gateway resolves STAFF_DIR and POLICY_DIR via __file__ automatically,
# but explicit env vars let the compose file override them if needed.
ENV STAFF_DIR=/app/services/staff \
    POLICY_DIR=/app/services/policy_proc \
    GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=8003

WORKDIR /app/services/ai_chatbot

EXPOSE 8003

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8003"]
