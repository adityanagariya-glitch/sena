# OCR API Routes (services/ocr/src/ocr/api/routes.py)
#
# Purpose: Defines all OCR service endpoints
#
# Endpoints:
#
# 1. GET /health (exempt from tenant context)
#    - Status: 200 OK
#    - Returns: HealthResponse
#    - Content:
#      - service: "sena-ocr"
#      - version: Service version
#      - status: "healthy" or "unhealthy"
#      - database: "connected" or "disconnected"
#    - Tests: Database connectivity
#    - Used by: Load balancers, monitoring systems
#
# 2. POST /extract (requires tenant context)
#    - Status: 501 Not Implemented (scaffolding only)
#    - Parameters:
#      - file: Document image (JPEG, PNG, PDF)
#      - document_type: Classification (drivers_licence, passport, medicare, etc.)
#    - Future implementation (Module 1):
#      1. Validate file type and size
#      2. Upload to temporary storage
#      3. Send to OCR cloud engine (AWS Textract, Azure AI Vision, etc.)
#      4. Post-process extracted fields
#      5. Store result in ocr_jobs table
#      6. Return extracted fields with confidence scores
#
#    - Returns error metadata:
#      - request_id: Correlation ID for tracing
#      - tenant_id: Organization ID
#      - document_type: What was submitted
#      - filename: Original filename
#
# Note: This is the Sprint 0 scaffold. Full implementation covers Module 1.
