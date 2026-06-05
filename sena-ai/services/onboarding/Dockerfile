FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY shared /app/shared
RUN pip install -U pip && pip install /app/shared

COPY services/onboarding/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/onboarding/src /app/src
ENV PYTHONPATH=/app/src

EXPOSE 8083

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8083/health/live').status==200 else 1)"

CMD ["uvicorn", "onboarding.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8083"]
