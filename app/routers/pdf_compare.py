"""Advanced PDF comparison endpoint."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import get_settings
from app.services.pdf_compare import compare_pdfs
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.validator import PDFValidationError, UnsupportedPDFError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["PDF Compare"])


async def _save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> None:
    total = 0
    with open(dest, "wb") as f:
        while chunk := await upload.read(1 << 20):
            total += len(chunk)
            if total > max_bytes:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds size limit")
            f.write(chunk)
    if total == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file")


@router.post(
    "/compare-pdf",
    summary="Compare two PDFs (text + visual + page structure)",
    description=(
        "Performs text diff, visual region diff, and page-level matching "
        "(added/deleted/reordered pages). Returns a JSON summary by default, or "
        "a downloadable HTML or PDF report when report_format is selected."
    ),
)
async def compare_pdf_endpoint(
    background_tasks: BackgroundTasks,
    original_pdf: UploadFile = File(..., description="Original / baseline PDF"),
    new_pdf: UploadFile = File(..., description="New / revised PDF"),
    report_format: str = Query("json", pattern="^(json|html|pdf)$"),
):
    settings = get_settings()
    _, job_dir = create_job_dir("compare")
    out_dir = job_dir / "output"

    orig_path = job_dir / "original.pdf"
    new_path = job_dir / "new.pdf"

    try:
        await _save_upload(original_pdf, orig_path, settings.max_pdf_size_bytes)
        await _save_upload(new_pdf, new_path, settings.max_pdf_size_bytes)

        result = compare_pdfs(orig_path, new_path, output_dir=out_dir)

        background_tasks.add_task(cleanup_job, job_dir)

        if report_format in ("html", "pdf"):
            report_path = out_dir / result.reports[report_format]
            media_type = "text/html" if report_format == "html" else "application/pdf"
            return FileResponse(
                report_path,
                media_type=media_type,
                filename=f"compare-report.{report_format}",
                background=background_tasks,
            )

        payload = result.model_dump()
        json_path = out_dir / result.reports["json"]
        payload["reports"]["json_content"] = json_path.read_text(encoding="utf-8")

        return JSONResponse(content=payload)

    except PDFValidationError as exc:
        cleanup_job(job_dir)
        raise HTTPException(400, str(exc)) from exc
    except UnsupportedPDFError as exc:
        cleanup_job(job_dir)
        raise HTTPException(415, str(exc)) from exc
    except HTTPException:
        cleanup_job(job_dir)
        raise
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("PDF compare failed")
        raise HTTPException(500, "Unable to compare the uploaded PDFs.") from exc
