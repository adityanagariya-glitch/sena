# Global Error Handler Middleware (shared/src/sena_common/middleware/error_handler.py)
#
# Purpose: Centralized error handling for all FastAPI services
#
# Custom Exceptions:
# 1. TenantIsolationError - Raised when tenant boundary is violated
#
# 2. ResourceNotFoundError - Raised when resource not found
#    - Stores resource type and identifier
#
# Response Format:
# All errors return standardized JSON:
# {
#   "status": "error",
#   "data": null,
#   "error": {
#     "code": "ERROR_CODE",
#     "message": "Human readable error message",
#     "details": [optional array of field-level errors]
#   }
# }
#
# Error Handlers (FastAPI exception handlers):
# 1. validation_exception_handler - 422 Validation errors
#    - Parses Pydantic field errors
#    - Returns field names and validation messages
#
# 2. http_exception_handler - 4xx/5xx HTTP errors
#    - Wraps standard FastAPI/Starlette exceptions
#
# 3. tenant_isolation_handler - 403 Tenant isolation violations
#    - Logs CRITICAL alert
#    - Returns generic "Access denied" message
#
# 4. resource_not_found_handler - 404 Resource not found
#    - Includes resource type and ID
#
# 5. unhandled_exception_handler - 500 Unexpected errors
#    - Logs full exception with traceback
#    - Returns generic error to prevent information leakage
#
# Registration: Handlers registered in FastAPI app via:
# app.add_exception_handler(Exception, unhandled_exception_handler)
