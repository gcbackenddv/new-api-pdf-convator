"""Endpoint for repairing corrupted or damaged PDF files."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.repair_service import repair_pdf
from app.services.pdf_processing.validator import PDFValidationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pdf", tags=["PDF Repair"])

_CHUNK_SIZE = 1024 * 1024


@router.post(
    "/repair",
    response_class=FileResponse,
    summary="Repair corrupted, damaged, or unreadable PDF files",
    description=(
        "Upload a damaged, corrupted, or malformed PDF to repair its structure.\n\n"
        "- Rebuilds corrupted or missing cross-reference (XREF) tables.\n"
        "- Re-indexes and recovers readable page trees and contents.\n"
        "- Rewrites and sanitizes PDF streams for compatibility with viewers.\n"
        "- Returns the repaired PDF as a download."
    ),
)
async def repair_pdf_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Damaged or corrupted PDF file to repair"),
) -> FileResponse:
    settings = get_settings()
    filename = file.filename or "document.pdf"
    clean_name = Path(filename).name

    _, job_dir = create_job_dir("repair")
    src = job_dir / "input.pdf"
    dst = job_dir / "output" / f"repaired_{clean_name}"

    try:
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

        result = await run_in_threadpool(repair_pdf, src, dst)

        background_tasks.add_task(cleanup_job, job_dir)

        headers = {
            "Cache-Control": "no-store",
            "X-PDF-Pages": str(result["page_count"]),
            "X-PDF-Repaired": "true" if result["was_repaired"] else "false",
            "Access-Control-Expose-Headers": "X-PDF-Pages, X-PDF-Repaired",
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
    except PDFValidationError as exc:
        cleanup_job(job_dir)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("repair-pdf failed unexpectedly")
        raise HTTPException(
            status_code=500, detail="Unable to repair the uploaded PDF."
        ) from exc

