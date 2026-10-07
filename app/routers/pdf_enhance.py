"""PDF enhancement endpoint."""
from __future__ import annotations

import io
import logging

import pymupdf as fitz
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from app.config import get_settings
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.enhance_service import enhance_pdf
from app.services.pdf_processing.enhancement import enhance_image
from app.services.pdf_processing.renderer import render_page_to_image
from app.services.pdf_processing.validator import (
    PDFValidationError,
    UnsupportedPDFError,
    validate_pdf,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pdf", tags=["PDF Enhance"])


@router.post("/enhance/preview", summary="Preview enhancement settings on the first PDF page")
async def enhance_preview_endpoint(
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
    _, job_dir = create_job_dir("enhance-preview")
    src = job_dir / "input.pdf"

    try:
        data = await file.read()
        if len(data) > settings.max_pdf_size_bytes:
            raise HTTPException(413, "File too large")
        src.write_bytes(data)
        validate_pdf(src)

        with fitz.open(src) as document:
            image = render_page_to_image(
                document,
                0,
                dpi=min(90, settings.MAX_RENDER_DPI),
            )
        image = enhance_image(
            image,
            grayscale=grayscale,
            contrast=contrast,
            brightness=brightness,
            sharpen=sharpen,
            denoise=denoise,
            threshold=threshold,
            background_cleanup=background_cleanup,
        )
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)
        return Response(
            content=buffer.getvalue(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except (PDFValidationError, UnsupportedPDFError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("enhance preview failed")
        raise HTTPException(500, "Unable to preview PDF enhancement.") from exc
    finally:
        cleanup_job(job_dir)


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
