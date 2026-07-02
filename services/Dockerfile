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
#
# Each service has its own requirements.txt for service-specific deps.
# services/requirements.base.txt is the shared base installed in every image.


# ── Base: shared Python env + sena-common ─────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.base.txt /tmp/requirements.base.txt
RUN pip install --no-cache-dir -r /tmp/requirements.base.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    find /opt/venv -type f -name "*.so" -exec strip {} \; 2>/dev/null || true && \
    rm -rf /tmp/requirements.base.txt /root/.cache

COPY shared /app/shared
RUN pip install --no-cache-dir /app/shared && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete

RUN rm -rf /root/.cache/pip

# ── Voice — case note dictation via Bedrock (port 8008) ───────────────────
FROM base AS voice

COPY voice/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /tmp/requirements.txt /root/.cache

RUN rm -rf /root/.cache/pip
COPY voice/ /app/voice/
WORKDIR /app
ENV PYTHONPATH=/app

EXPOSE 8008

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8008'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{p}/health/live').status==200 else 1)"

CMD uvicorn voice.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8008}


# ── Onboarding — Gemini Live voice onboarding (port 8009) ─────────────────
FROM base AS onboarding

COPY onboarding/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /tmp/requirements.txt /root/.cache

RUN rm -rf /root/.cache/pip

COPY onboarding/ /app/onboarding/
WORKDIR /app
ENV PYTHONPATH=/app:/app/onboarding

EXPOSE 8009

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('SENA_AI_ONBOARDING_PORT','8009'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{p}/health/live').status==200 else 1)"

CMD uvicorn onboarding.main:create_app --factory --host 0.0.0.0 --port ${SENA_AI_ONBOARDING_PORT:-8009}


# ── Case Review — RP-detection + voice pipeline (port 8002) ───────────────
FROM base AS case-review

COPY case_review/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /tmp/requirements.txt /root/.cache

RUN rm -rf /root/.cache/pip

COPY case_review/ /app/case_review/
WORKDIR /app/case_review
ENV PYTHONPATH=/app:/app/case_review

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('SENA_AI_CASE_REVIEW_PORT','8002'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{p}/v1/restrictive-practices/health').status==200 else 1)"

CMD uvicorn main:create_app --factory --host 0.0.0.0 --port ${SENA_AI_CASE_REVIEW_PORT:-8002}


# ── Casenote Monthly — NDIS report generator via Bedrock (port 8004) ──────
FROM base AS casenote-monthly

COPY casenote_monthly/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /tmp/requirements.txt /root/.cache

RUN rm -rf /root/.cache/pip

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
     casenote_monthly/rsa_auth.py \
     casenote_monthly/outbound_sign.py \
     /app/

WORKDIR /app

EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8004/psr-report/health').status==200 else 1)"

CMD ["uvicorn", "api_main:app", "--host", "0.0.0.0", "--port", "8004"]


# ── Policy Proc — policy & procedures via Bedrock (port 8000) ─────────────
FROM base AS policy-proc

COPY policy_proc/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /tmp/requirements.txt /root/.cache

RUN rm -rf /root/.cache/pip

COPY policy_proc /app/policy_proc
WORKDIR /app/policy_proc
ENV PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ── Staff API — shifts & client information via Bedrock (port 8001) ────────
FROM base AS staff

# base covers all deps for staff (boto3, fastapi, jwt, msgspec, pydantic, requests)
COPY staff /app/staff
WORKDIR /app/staff
ENV PYTHONPATH=/app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"

CMD ["uvicorn", "api_main:app", "--host", "0.0.0.0", "--port", "8001"]


# ── AI Chatbot — routing gateway (port 8003) ──────────────────────────────
FROM base AS ai-chatbot

# base covers all deps for ai_chatbot (boto3, cryptography, fastapi, httpx, pydantic)
COPY ai_chatbot /app/services/ai_chatbot
ENV PYTHONPATH=/app \
    GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=8003
WORKDIR /app/services/ai_chatbot

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8003/ai-chatbot/healthz').status==200 else 1)"

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8003"]


# ── AI Communication Log — classifier via Bedrock (port 8005) ─────────────
FROM base AS ai-communication-log

# base covers all deps for ai-communication-log (boto3, fastapi, pydantic, pydantic_settings)
COPY ai-communication-log/ai-classifier /app
WORKDIR /app
ENV PYTHONPATH=/app

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8005/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]


# ── Shift Summary — summary consolidation via Bedrock (port 8006) ─────────
FROM base AS shift-summary

# base covers all deps for shift-summary (boto3, fastapi, pydantic, pydantic_settings)
COPY shift-summary /app
WORKDIR /app

EXPOSE 8006

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8006/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]


# ── AI Text Extraction — identity-document field extraction (port 8007) ───
FROM base AS ai-text-extraction

COPY ai-text-extraction/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /tmp/requirements.txt /root/.cache
RUN rm -rf /root/.cache/pip

COPY ai-text-extraction/scripts /app/scripts
WORKDIR /app
ENV PYTHONPATH=/app

EXPOSE 8007

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8007/health').status==200 else 1)"

CMD ["uvicorn", "scripts.api:app", "--host", "0.0.0.0", "--port", "8007"]


# ── Doc Service — document ingestion + Bedrock KB management (port 8010) ──
FROM base AS doc-service

COPY doc_service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    find /opt/venv -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /tmp/requirements.txt /root/.cache
RUN rm -rf /root/.cache/pip
COPY doc_service /app/doc_service
WORKDIR /app/doc_service
ENV PYTHONPATH=/app/doc_service

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8010/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
