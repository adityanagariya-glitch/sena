# Schemas Package (shared/src/sena_common/schemas/__init__.py)
#
# Purpose: Pydantic models for API requests/responses
#
# Contents:
# - responses.py: Standard response envelopes
#   - ApiResponse[T]: Generic response with status/data/error
#   - HealthResponse: Service health check
#   - ResponseMetadata: Request ID, tenant ID, timestamp
#
# - errors.py: Error response helpers
