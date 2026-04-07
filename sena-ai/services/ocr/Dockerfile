# Dockerfile for OCR Service
# Builds a Python 3.12 container for the OCR document processing service
#
# Build stages:
# 1. Base image: python:3.12-slim (lightweight official Python image)
# 2. Install shared library (sena-common) from pyproject.toml
# 3. Install OCR service dependencies
# 4. Copy service source code
# 5. Set PYTHONPATH to include src and shared/src
#
# Runtime:
# - Starts Uvicorn ASGI server
# - Runs FastAPI app factory (ocr.main:create_app)
# - Listens on port 8000
# - Enables auto-reload for development
