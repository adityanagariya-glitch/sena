from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from models.schemas import CaseNoteInput, PipelineResult
from pipeline.graph import run_pipeline

router = APIRouter(prefix="/v1/restrictive-practices", tags=["restrictive-practices"])


@router.post("/evaluate", response_model=PipelineResult)
async def evaluate_case_note(
    payload: CaseNoteInput,
    db: AsyncSession = Depends(get_db),
) -> PipelineResult:
    """Run a case note through the full restrictive practice detection pipeline."""
    return await run_pipeline(payload, db)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "restrictive-practice-detection"}
