"""PDF enhancement endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.enhance_service import enhance_pdf
from app.services.pdf_processing.validator import PDFValidationError, UnsupportedPDFError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pdf", tags=["PDF Enhance"])


@router.post("/enhance", summary="Enhance scanned PDF pages (contrast, denoise, etc.)")
async def enhance_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    grayscale: bool = Query(False),
    contrast: float = Query(1.15, ge=0.5, le=3.0),
    brightness: float = Query(1.05, ge=0.5, le=2.0),
    sharpen: float = Query(0.3, ge=0.0, le=2.0),
    denoise: bool = Query(False),
    threshold: bool = Query(False),
    background_cleanup: bool = Query(False),
):
    settings = get_settings()
    job_id, job_dir = create_job_dir("enhance")
    src = job_dir / "input.pdf"
    dst = job_dir / "output" / "enhanced.pdf"

    try:
        data = await file.read()
        if len(data) > settings.max_pdf_size_bytes:
            raise HTTPException(413, "File too large")
        src.write_bytes(data)
        enhance_pdf(
            src, dst,
            grayscale=grayscale,
            contrast=contrast,
            brightness=brightness,
            sharpen=sharpen,
            denoise=denoise,
            threshold=threshold,
            background_cleanup=background_cleanup,
        )
        background_tasks.add_task(cleanup_job, job_dir)
        return FileResponse(dst, media_type="application/pdf", filename="enhanced.pdf", background=background_tasks)
    except (PDFValidationError, UnsupportedPDFError) as exc:
        cleanup_job(job_dir)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("enhance failed")
        raise HTTPException(500, "Unable to enhance PDF.") from exc
