import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from models.schemas import CaseNoteInput, PipelineResult
from pipeline.graph import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/restrictive-practices", tags=["restrictive-practices"])


@router.post("/evaluate", response_model=PipelineResult)
async def evaluate_case_note(
    payload: CaseNoteInput,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> PipelineResult:
    """Run a case note through the full restrictive practice detection pipeline."""
    response.headers["X-Privacy-Classification"] = "Sensitive-Health-Information-APP3"
    response.headers["X-Data-Retention"] = "No-Retention-Session-Only"
    try:
        return await run_pipeline(payload, db)
    except Exception as exc:
        logger.error(
            "Pipeline error case_note_id=%s: %s",
            payload.case_note_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "restrictive-practice-detection"}
