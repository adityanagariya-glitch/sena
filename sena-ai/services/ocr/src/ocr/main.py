# OCR Service FastAPI Application (services/ocr/src/ocr/main.py)
#
# Purpose: Application factory and configuration for OCR service
# This is the reference scaffold that all future Sena AI services follow
#
# Function: create_app(settings=None)
# - Creates and configures FastAPI application
# - Registers all middleware, exception handlers, routers
# - Returns configured app instance
#
# Lifespan manager (startup/shutdown):
# - Startup: Initializes database engine with connection pool
# - Shutdown: Closes all connections and cleans up
#
# Middleware stack (order matters - outermost first)
# 1. RequestIDMiddleware - Generates/propagates correlation IDs
# 2. TenantMiddleware - Extracts and validates tenant context
#
# Exception handlers registered:
# - RequestValidationError (422) - Pydantic validation failures
# - StarletteHTTPException (4xx/5xx) - HTTP errors
# - TenantIsolationError (403) - Tenant boundary violations
# - ResourceNotFoundError (404) - Missing resources
# - Exception (500) - Catch-all for unhandled exceptions
#
# Routers registered:
# - /v1/ocr/* - OCR API endpoints
#
# Configuration:
# - Docs endpoint (/docs) only enabled in development
# - Uses FastAPI app factory pattern for testing
#
# Usage:
# In Dockerfile: CMD ["uvicorn", "ocr.main:create_app", "--factory"]
# The --factory flag tells Uvicorn to call create_app() to get the app instance
