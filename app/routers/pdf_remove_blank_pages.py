"""Endpoint for removing blank pages from PDF files."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.remove_blank_pages import (
    PDFAllPagesBlankError,
    PDFProcessingError,
    PDFTimeoutError,
    remove_blank_pages,
)
from app.services.pdf_processing.validator import (
    PDFValidationError,
    UnsupportedPDFError,
    validate_pdf,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pdf", tags=["PDF Remove Blank Pages"])

_ACCEPTED_EXTENSIONS = (".pdf",)
_CHUNK_SIZE = 1024 * 1024  # 1 MB


@router.post(
    "/remove-blank-pages",
    response_class=FileResponse,
    summary="Detect and remove genuinely blank pages from a PDF",
    description=(
        "Upload a PDF to detect and remove genuinely blank pages.\n\n"
        "- Works with text-based PDFs and scanned/image-based documents.\n"
        "- Preserves pages with text, images, drawings, annotations, and small content.\n"
        "- Preserves the original page order and PDF rendering quality.\n"
        "- Returns the cleaned PDF along with metadata headers: "
        "`X-Original-Pages`, `X-Removed-Pages`, `X-Remaining-Pages`, and `X-Removed-Page-Numbers`."
    ),
    responses={
        200: {
            "description": "The cleaned PDF without blank pages.",
            "content": {"application/pdf": {}},
            "headers": {
                "X-Original-Pages": {
                    "description": "Total pages in the original PDF",
                    "schema": {"type": "integer"},
                },
                "X-Removed-Pages": {
                    "description": "Number of blank pages removed",
                    "schema": {"type": "integer"},
                },
                "X-Remaining-Pages": {
                    "description": "Number of pages remaining in cleaned PDF",
                    "schema": {"type": "integer"},
                },
                "X-Removed-Page-Numbers": {
                    "description": "JSON array of removed 1-indexed page numbers",
                    "schema": {"type": "string"},
                },
            },
        },
        400: {"description": "Invalid PDF upload or corrupted file structure."},
        413: {"description": "Upload size exceeds the configured maximum limit."},
        415: {"description": "File is not a valid PDF."},
        422: {"description": "All pages are blank, or PDF is encrypted / password protected."},
        504: {"description": "Processing exceeded the configured timeout limit."},
    },
)
async def remove_blank_pages_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF file to remove blank pages from"),
    threshold: float | None = Query(
        None,
        ge=0.0,
        le=1.0,
        description="Detection threshold (dark pixel ratio). Defaults to configured BLANK_PAGE_THRESHOLD (0.0005).",
    ),
) -> FileResponse:
    settings = get_settings()

    # Extension check
    filename = file.filename or "document.pdf"
    clean_name = Path(filename).name
    if not clean_name.lower().endswith(_ACCEPTED_EXTENSIONS):
        raise HTTPException(
            status_code=415,
            detail="The uploaded file does not appear to be a PDF (invalid extension).",
        )

    # Job directory allocation
    _, job_dir = create_job_dir(settings.REMOVE_BLANK_PAGES_DIRNAME)
    src = job_dir / "input.pdf"
    dst = job_dir / "output" / f"cleaned_{clean_name}"

    try:
        # Stream upload to disk in chunks to avoid memory spikes
        total_size = 0
        max_bytes = settings.max_pdf_size_bytes

        with open(src, "wb") as f:
            while chunk := await file.read(_CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"PDF exceeds maximum allowed size of {settings.MAX_PDF_SIZE_MB} MB.",
                    )
                f.write(chunk)

        if total_size == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        # Run CPU/image analysis in worker threadpool to prevent blocking FastAPI event loop
        result = await run_in_threadpool(
            remove_blank_pages,
            src,
            dst,
            threshold=threshold,
        )

        # Schedule temp directory cleanup after response transmission
        background_tasks.add_task(cleanup_job, job_dir)

        headers = {
            "Cache-Control": "no-store",
            "X-Original-Pages": str(result["original_page_count"]),
            "X-Removed-Pages": str(result["removed_page_count"]),
            "X-Remaining-Pages": str(result["remaining_page_count"]),
            "X-Removed-Page-Numbers": json.dumps(result["removed_page_numbers"]),
            "Access-Control-Expose-Headers": (
                "X-Original-Pages, X-Removed-Pages, X-Remaining-Pages, X-Removed-Page-Numbers"
            ),
        }

        return FileResponse(
            path=dst,
            media_type="application/pdf",
            filename=dst.name,
            headers=headers,
            background=background_tasks,
        )

    except HTTPException:
        cleanup_job(job_dir)
        raise
    except PDFAllPagesBlankError as exc:
        cleanup_job(job_dir)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnsupportedPDFError as exc:
        cleanup_job(job_dir)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PDFValidationError as exc:
        cleanup_job(job_dir)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PDFTimeoutError as exc:
        cleanup_job(job_dir)
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("remove-blank-pages failed unexpectedly")
        raise HTTPException(
            status_code=500, detail="Unable to process and remove blank pages from the PDF."
        ) from exc
