"""Endpoint for repairing corrupted or damaged PDF files."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.config import get_settings
from app.output import safe_stem
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_repair import repair_pdf, PDFRepairError

logger = logging.getLogger(__name__)
# Both /repair-pdf (root level) and /api/v1/pdf/repair for consistency across existing endpoints
router = APIRouter(tags=["PDF Repair"])

_CHUNK_SIZE = 1024 * 1024


async def _handle_repair_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile,
) -> FileResponse:
    settings = get_settings()

    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file.")

    clean_stem = safe_stem(filename)
    repaired_filename = f"repaired_{clean_stem}.pdf"

    _, job_dir = create_job_dir("repair")
    src = job_dir / "input.pdf"
    dst = job_dir / "output" / repaired_filename

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

        # Execute repair with validation in worker thread pool
        result = await run_in_threadpool(repair_pdf, src, dst)

        background_tasks.add_task(cleanup_job, job_dir)

        headers = {
            "Cache-Control": "no-store",
            "X-PDF-Pages": str(result.page_count),
            "X-PDF-Repaired": "true" if result.was_repaired else "false",
            "X-PDF-Repair-Method": result.repair_method,
            "Access-Control-Expose-Headers": "X-PDF-Pages, X-PDF-Repaired, X-PDF-Repair-Method",
        }

        return FileResponse(
            path=dst,
            media_type="application/pdf",
            filename=repaired_filename,
            headers=headers,
            background=background_tasks,
        )

    except HTTPException:
        cleanup_job(job_dir)
        raise
    except PDFRepairError as exc:
        cleanup_job(job_dir)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("repair-pdf failed unexpectedly")
        raise HTTPException(
            status_code=500, detail="Unable to repair the uploaded PDF."
        ) from exc


@router.post(
    "/repair-pdf",
    response_class=FileResponse,
    summary="Repair damaged, corrupted, or malformed PDF file",
    description=(
        "Upload a damaged, corrupted, or malformed PDF to repair its structure.\n\n"
        "- Rebuilds corrupted or missing cross-reference (XREF) tables.\n"
        "- Restores broken page tree structures and invalid object references.\n"
        "- Fixes damaged streams and metadata while preserving text and images.\n"
        "- Strictly validates the repaired PDF before delivering download."
    ),
)
async def repair_pdf_route(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Damaged or corrupted PDF file to repair"),
) -> FileResponse:
    return await _handle_repair_upload(background_tasks, file)


@router.post(
    "/api/v1/pdf/repair",
    response_class=FileResponse,
    summary="Repair damaged, corrupted, or malformed PDF file (v1 API)",
    description="Alias route for /repair-pdf.",
)
async def repair_pdf_v1_route(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Damaged or corrupted PDF file to repair"),
) -> FileResponse:
    return await _handle_repair_upload(background_tasks, file)

