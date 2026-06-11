# Unified multi-stage Dockerfile for all SENA AI services.
#
# Build context = services/ directory (where this file lives).
# All COPY paths are relative to services/.
#
# Build via compose (from repo root):
#   docker compose -f services/docker-compose.deploy.yml up --build
#
# Build a single stage manually (from services/):
#   docker build --target voice -t sena-voice .

# ── Base: shared Python env + sena-common ─────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install -U pip


# Create virtual environment for shared dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install all dependencies (merged from all services) in one shot
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
# shared/ lives inside services/ — same level as this Dockerfile
COPY shared /app/shared
RUN pip install /app/shared


# ── Voice — case note dictation via Bedrock (port 8008) ───────────────────
FROM base AS voice

# Copy voice package (flat structure: no src/ subdirectory)
# Excludes: tests/, __pycache__, .git, *.pyc (handled by .dockerignore)
COPY voice/ /app/voice/

WORKDIR /app
ENV PYTHONPATH=/app

EXPOSE 8008

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8008/health/live').status==200 else 1)"

CMD ["uvicorn", "voice.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8008"]


# ── Onboarding — Gemini Live voice onboarding (port 8009) ─────────────────
FROM base AS onboarding

# Copy onboarding package (flat structure: no src/ subdirectory)
# Excludes: tests/, __pycache__, .git, *.pyc (handled by .dockerignore)
COPY onboarding/ /app/onboarding/

WORKDIR /app
ENV PYTHONPATH=/app

EXPOSE 8009

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8009/health/live').status==200 else 1)"

CMD ["uvicorn", "onboarding.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8009"]


# ── Case Review — pgvector intelligence layer (port 8002) ─────────────────
FROM base AS case-review

COPY case_review/pyproject.toml /app/pyproject.toml
COPY case_review/src /app/src
RUN pip install .

ENV PYTHONPATH=/app/src

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health/live').status==200 else 1)"

CMD ["uvicorn", "case_review.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8002"]


# ── Casenote Monthly — NDIS report generator via Bedrock (port 8004) ──────
FROM base AS casenote-monthly

# Copy only the Python source files — exclude .env, __pycache__, out/, reports/
COPY casenote_monthly/api_main.py \
     casenote_monthly/auth.py \
     casenote_monthly/config.py \
     casenote_monthly/cleaner.py \
     casenote_monthly/prompt.py \
     casenote_monthly/dates.py \
     casenote_monthly/guardrails.py \
     casenote_monthly/agents_types.py \
     casenote_monthly/bedrock_client.py \
     casenote_monthly/bedrock_retry.py \
     casenote_monthly/linter.py \
     casenote_monthly/stats.py \
     casenote_monthly/trend_store.py \
     /app/

WORKDIR /app

EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8004/psr-report/health').status==200 else 1)"

CMD ["uvicorn", "api_main:app", "--host", "0.0.0.0", "--port", "8004"]


# ── Policy Proc — policy & procedures via Bedrock (port 8000) ────────────
FROM base AS policy-proc

COPY policy_proc /app/policy_proc
WORKDIR /app/policy_proc

ENV PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ── Staff API — shifts & client information via Bedrock (port 8001) ────────
FROM base AS staff

COPY staff /app/staff
WORKDIR /app/staff

ENV PYTHONPATH=/app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"

CMD ["uvicorn", "api_main:app", "--host", "0.0.0.0", "--port", "8001"]


# ── AI Chatbot — routing gateway (port 8003) ──────────────────────────────
#
# Network mode (docker-compose deploy): the gateway talks to the standalone
# sena-staff / sena-policy-proc containers over the docker network, so it does
# NOT bundle or spawn their code. boto3 (router's classifier) and PyJWT are
# already provided by the base requirements.txt.
#
# To run staff + policy as in-process children instead (local one-command dev
# via run.sh), set MANAGE_CHILDREN=true and COPY the staff + policy_proc trees
# back in below.
FROM base AS ai-chatbot

# Gateway code only — staff/policy run as their own containers.
COPY ai_chatbot  /app/services/ai_chatbot

ENV PYTHONPATH=/app \
    GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=8003

WORKDIR /app/services/ai_chatbot

EXPOSE 8003

# Short start-period: the gateway no longer spawns/health-gates children, it just
# needs its own HTTP server up. (compose depends_on gates on the backends being
# healthy before this container even starts.)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8003/ai-chatbot/healthz').status==200 else 1)"

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8003"]


# ── AI Communication Log — classifier via Bedrock (port 8005) ─────────────
FROM base AS ai-communication-log

# Code lives in ai-classifier/ — copy its contents to /app so `app.main:app` resolves
COPY ai-communication-log/ai-classifier /app

WORKDIR /app

ENV PYTHONPATH=/app

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8005/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]


# ── Shift Summary — summary consolidation via Bedrock (port 8006) ────────────
FROM base AS shift-summary

COPY shift-summary /app

WORKDIR /app

EXPOSE 8006

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8006/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]


# ── AI Text Extraction — identity-document field extraction via Bedrock Nova Lite (port 8007) ──
FROM base AS ai-text-extraction

# Code uses absolute `scripts.*` imports — keep the scripts/ package under /app
COPY ai-text-extraction/scripts /app/scripts

WORKDIR /app
ENV PYTHONPATH=/app

EXPOSE 8007

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8007/health').status==200 else 1)"

CMD ["uvicorn", "scripts.api:app", "--host", "0.0.0.0", "--port", "8007"]
