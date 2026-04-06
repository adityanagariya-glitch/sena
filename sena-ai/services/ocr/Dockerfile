FROM python:3.12-slim

WORKDIR /app

# Install shared library
COPY shared/pyproject.toml /app/shared/pyproject.toml
COPY shared/src /app/shared/src
RUN pip install --no-cache-dir /app/shared

# Install service dependencies
COPY services/ocr/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .

# Copy service source
COPY services/ocr/src /app/src

ENV PYTHONPATH=/app/src:/app/shared/src

CMD ["uvicorn", "ocr.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]
