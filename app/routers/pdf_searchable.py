"""Make PDF searchable (OCR text layer)."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.ocr import OCRProcessingError, OCRUnavailableError
from app.services.pdf_processing.searchable import make_searchable
from app.services.pdf_processing.validator import PDFValidationError, UnsupportedPDFError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pdf", tags=["PDF Searchable / OCR"])


@router.post(
    "/make-searchable",
    summary="Add invisible OCR text layer to scanned PDF pages",
)
async def make_searchable_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    lang: str = Query(None, description="Tesseract language(s), e.g. 'auto' or 'eng+ben'. Defaults to auto-detection/installed."),
    force_ocr: bool = Query(False, description="Force OCR on all pages even if text is present"),
    deskew: bool = Query(False, description="Automatically deskew tilted pages before OCR"),
    auto_rotate: bool = Query(False, description="Automatically correct page rotation (0/90/180/270)"),
):
    settings = get_settings()
    job_id, job_dir = create_job_dir("searchable")
    src = job_dir / "input.pdf"
    dst = job_dir / "output" / "searchable.pdf"

    try:
        data = await file.read()
        if len(data) > settings.max_pdf_size_bytes:
            raise HTTPException(413, "File too large")
        if not data:
            raise HTTPException(400, "Empty file")
        src.write_bytes(data)

        result = make_searchable(
            src,
            dst,
            lang=lang,
            force_ocr=force_ocr,
            deskew=deskew,
            auto_rotate=auto_rotate,
        )
        background_tasks.add_task(cleanup_job, job_dir)
        return FileResponse(
            dst,
            media_type="application/pdf",
            filename="searchable.pdf",
            headers={
                "X-OCR-Pages": str(result["pages_ocrd"]),
                "X-OCR-Words": str(result["words_recognized"]),
                "X-OCR-Pages-Skipped": str(result["pages_skipped"]),
            },
            background=background_tasks,
        )
    except OCRUnavailableError as exc:
        cleanup_job(job_dir)
        raise HTTPException(503, str(exc)) from exc
    except OCRProcessingError as exc:
        cleanup_job(job_dir)
        raise HTTPException(422, str(exc)) from exc
    except PDFValidationError as exc:
        cleanup_job(job_dir)
        raise HTTPException(400, str(exc)) from exc
    except UnsupportedPDFError as exc:
        cleanup_job(job_dir)
        raise HTTPException(415, str(exc)) from exc
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("make-searchable failed")
        raise HTTPException(500, "Unable to create searchable PDF.") from exc
