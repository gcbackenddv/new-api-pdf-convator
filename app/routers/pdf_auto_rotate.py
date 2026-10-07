"""PDF auto-rotate endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.orient_service import auto_rotate_pdf
from app.services.pdf_processing.validator import PDFValidationError, UnsupportedPDFError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pdf", tags=["PDF Auto-Rotate"])


@router.post("/auto-rotate", summary="Detect and correct page orientation (0/90/180/270)")
async def auto_rotate_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    settings = get_settings()
    job_id, job_dir = create_job_dir("orient")
    src = job_dir / "input.pdf"
    dst = job_dir / "output" / "rotated.pdf"

    try:
        data = await file.read()
        if len(data) > settings.max_pdf_size_bytes:
            raise HTTPException(413, "File too large")
        src.write_bytes(data)
        auto_rotate_pdf(src, dst)
        background_tasks.add_task(cleanup_job, job_dir)
        return FileResponse(dst, media_type="application/pdf", filename="rotated.pdf", background=background_tasks)
    except (PDFValidationError, UnsupportedPDFError) as exc:
        cleanup_job(job_dir)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("auto-rotate failed")
        raise HTTPException(500, "Unable to auto-rotate PDF.") from exc
