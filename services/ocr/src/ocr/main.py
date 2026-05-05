"""Minimal OCR service stub. Real implementation pending."""
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="SENA OCR Service")

    @app.get("/health/live")
    async def health() -> dict:
        return {"status": "alive", "service": "ocr"}

    return app
