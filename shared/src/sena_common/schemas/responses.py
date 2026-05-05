# Standard Response Schemas (shared/src/sena_common/schemas/responses.py)
#
# Purpose: Pydantic models for standardized API responses
#
# Models:
# 1. ResponseMetadata
#    - request_id: Correlation ID for request tracing
#    - tenant_id: Tenant UUID from context
#    - timestamp: ISO 8601 UTC timestamp
#
# 2. ApiResponse[T] (Generic)
#    - status: "success" or "error"
#    - data: Response payload (type T)
#    - error: Error details (if status is "error")
#    - metadata: Metadata about the response
#
#    Example success:
#    {
#      "status": "success",
#      "data": { "id": "123", "name": "Report" },
#      "error": null,
#      "metadata": { "request_id": "xyz", "tenant_id": "abc", "timestamp": "2025-01-01T00:00:00Z" }
#    }
#
# 3. HealthResponse
#    - service: Service name (e.g., "Sena OCR Service")
#    - version: Service version
#    - status: "healthy" or "unhealthy"
#    - database: "connected" or "disconnected"
#
# Usage:
# - Endpoint return type: ApiResponse[YourDataModel]
# - FastAPI automatically serializes to JSON
# - Validation happens automatically
