FROM python:3.12-slim

WORKDIR /app

COPY services/voice/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

COPY services/voice/src /app/src
ENV PYTHONPATH=/app/src

EXPOSE 8082

CMD ["uvicorn", "voice.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8082"]
