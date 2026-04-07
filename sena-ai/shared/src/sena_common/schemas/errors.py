# Error Response Helper (shared/src/sena_common/schemas/errors.py)
#
# Purpose: Helper function for building standard error responses
#
# Function: error_response(status_code, code, message, details=None)
# Parameters:
# - status_code: HTTP status code (e.g., 400, 401, 403, 404, 422, 500)
# - code: Error code constant (e.g., VALIDATION_ERROR, RESOURCE_NOT_FOUND)
# - message: Human-readable error message
# - details: Optional array of field-level errors
#
# Returns:
# JSONResponse with format:
# {
#   "status": "error",
#   "data": null,
#   "error": {
#     "code": "ERROR_CODE",
#     "message": "Error description",
#     "details": [optional field errors]
#   }
# }
#
# Usage:
# Used by middleware and exception handlers
# Example: error_response(401, "TENANT_RESOLUTION_FAILED", "Missing X-Tenant-ID header")
