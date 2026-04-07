"""OCR API routes."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse

from sena_common.db.session import get_session
from sena_common.middleware.tenant_context import get_tenant_context
from sena_common.middleware.request_id import get_request_id
from sena_common.schemas.responses import HealthResponse

from ocr.core.config import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Health check endpoint. Exempt from tenant context."""
    settings = get_settings()

    # Test database connectivity
    db_status = "connected"
    try:
        from sena_common.db.session import get_session_no_tenant

        async with get_session_no_tenant() as session:
            from sqlalchemy import text

            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    return HealthResponse(
        service=settings.service_name,
        version=settings.service_version,
        status="healthy" if db_status == "connected" else "unhealthy",
        database=db_status,
    )


@router.post("/extract")
async def extract_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
) -> JSONResponse:
    """Extract structured data from an uploaded document image.

    This is the scaffold endpoint. The actual OCR processing logic
    will be implemented in Module 1 development.

    Args:
        file: The document image (JPEG, PNG, PDF)
        document_type: Type of document (e.g., 'drivers_licence', 'passport', 'medicare')
    """
    ctx = get_tenant_context()
    request_id = get_request_id()

    # TODO: Implement OCR processing pipeline (Module 1)
    # 1. Validate file type and size
    # 2. Upload to temporary storage
    # 3. Send to OCR engine (cloud provider dependent — TBD)
    # 4. Post-process extracted fields
    # 5. Store result in ocr_jobs table
    # 6. Return extracted fields with confidence scores

    return JSONResponse(
        status_code=501,
        content={
            "status": "error",
            "data": None,
            "error": {
                "code": "NOT_IMPLEMENTED",
                "message": "OCR extraction not yet implemented. This is the Sprint 0 scaffold.",
            },
            "metadata": {
                "request_id": request_id,
                "tenant_id": str(ctx.tenant_id),
                "document_type": document_type,
                "filename": file.filename,
            },
        },
    )
