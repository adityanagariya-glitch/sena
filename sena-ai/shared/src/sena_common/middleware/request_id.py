# Request ID Middleware (shared/src/sena_common/middleware/request_id.py)
#
# Purpose: Generates or propagates correlation IDs for distributed tracing
#
# How it works:
# 1. On each request, middleware checks for X-Request-ID header
# 2. If present, uses provided ID; otherwise generates UUID
# 3. Stores ID in ContextVar for duration of request
# 4. Includes ID in response headers for client reference
#
# ContextVar: _request_id_var
# - Thread-safe, async-aware context manager
# - Accessible via get_request_id() anywhere in request lifecycle
#
# Functions:
# - get_request_id() - Returns current request ID
# - RequestIDMiddleware - FastAPI middleware class
#
# Usage:
# - Development: Tools can provide custom X-Request-ID headers
# - Logging: Log handlers include request_id via context
# - Tracing: Distributed tracing systems use this ID to correlate spans
#
# Response: Adds X-Request-ID header to response for client tracking
