# OCR Service Route Tests (services/ocr/tests/test_routes.py)
#
# Purpose: Unit tests for OCR API endpoints
#
# Test fixtures:
# - app: FastAPI app instance
# - client: Async HTTP client for testing
#
# Tests:
#
# 1. test_health_check_returns_200
#    - Tests: GET /v1/ocr/health
#    - Expects: 200 OK
#    - Verifies: Service name, status field
#    - Exempt from tenant context requirements
#
# 2. test_extract_rejects_without_tenant_id
#    - Tests: POST /v1/ocr/extract without X-Tenant-ID header
#    - Expects: 401 Unauthorized
#    - Error code: TENANT_RESOLUTION_FAILED
#    - Verifies: Tenant middleware is enforcing context requirement
#
# 3. test_extract_with_tenant_returns_501_scaffold
#    - Tests: POST /v1/ocr/extract with valid tenant headers
#    - Expects: 501 Not Implemented (scaffold phase)
#    - Verifies:
#      - Tenant context is properly set
#      - Request metadata included in response
#      - Tenant ID persisted through middleware stack
#
# Note: These are scaffold tests for Sprint 0.
# Full OCR functionality tests will be added in Module 1.
