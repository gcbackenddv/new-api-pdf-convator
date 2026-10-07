"""PDF deskew endpoint."""
from __future__ import annotations

import base64
import io
import json
import logging

import pymupdf as fitz
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.services.pdf_processing.pipeline import create_job_dir, cleanup_job
from app.services.pdf_processing.deskew_service import deskew_pdf
from app.services.pdf_processing.renderer import render_page_to_image
from app.services.pdf_processing.validator import PDFValidationError, UnsupportedPDFError, validate_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/pdf", tags=["PDF Deskew"])


@router.post("/deskew/preview", summary="Render page previews for manual deskew")
async def deskew_preview_endpoint(file: UploadFile = File(...)):
    settings = get_settings()
    _, job_dir = create_job_dir("deskew-preview")
    src = job_dir / "input.pdf"

    try:
        data = await file.read()
        if len(data) > settings.max_pdf_size_bytes:
            raise HTTPException(413, "File too large")
        src.write_bytes(data)
        page_count = validate_pdf(src)

        with fitz.open(src) as document:
            pages = []
            for page_index in range(page_count):
                image = render_page_to_image(
                    document,
                    page_index,
                    dpi=min(55, settings.MAX_RENDER_DPI),
                )
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=60, optimize=True)
                pages.append({
                    "page": page_index + 1,
                    "preview": base64.b64encode(buffer.getvalue()).decode("ascii"),
                })
        return {"pages": pages}
    except (PDFValidationError, UnsupportedPDFError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("deskew preview failed")
        raise HTTPException(500, "Unable to preview the uploaded PDF.") from exc
    finally:
        cleanup_job(job_dir)


@router.post(
    "/deskew",
    summary="Straighten PDF pages automatically or with per-page angles",
)
async def deskew_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    manual_angle: float | None = Query(
        None,
        ge=-15,
        le=15,
        description="Manual clockwise rotation in degrees; omitted for automatic deskew.",
    ),
    manual_angles_json: str | None = Form(
        None,
        alias="manual_angles",
        description="JSON array of clockwise rotation angles, one per page.",
    ),
):
    settings = get_settings()
    _, job_dir = create_job_dir("deskew")
    src = job_dir / "input.pdf"
    dst = job_dir / "output" / "deskewed.pdf"

    try:
        data = await file.read()
        if len(data) > settings.max_pdf_size_bytes:
            raise HTTPException(413, "File too large")
        src.write_bytes(data)
        manual_angles = None
        if manual_angles_json is not None:
            if manual_angle is not None:
                raise HTTPException(422, "Use either manual_angle or manual_angles, not both.")
            try:
                parsed_angles = json.loads(manual_angles_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(422, "manual_angles must be a JSON array.") from exc
            if (
                not isinstance(parsed_angles, list)
                or any(
                    isinstance(angle, bool)
                    or not isinstance(angle, (int, float))
                    or not -15 <= angle <= 15
                    for angle in parsed_angles
                )
            ):
                raise HTTPException(
                    422,
                    "manual_angles must be an array of numbers between -15 and 15.",
                )
            page_count = validate_pdf(src)
            if len(parsed_angles) != page_count:
                raise HTTPException(
                    422,
                    f"manual_angles must contain exactly {page_count} page values.",
                )
            manual_angles = [float(angle) for angle in parsed_angles]
        deskew_pdf(src, dst, manual_angle=manual_angle, manual_angles=manual_angles)
        background_tasks.add_task(cleanup_job, job_dir)
        return FileResponse(dst, media_type="application/pdf", filename="deskewed.pdf", background=background_tasks)
    except HTTPException:
        cleanup_job(job_dir)
        raise
    except (PDFValidationError, UnsupportedPDFError) as exc:
        cleanup_job(job_dir)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        cleanup_job(job_dir)
        logger.exception("deskew failed")
        raise HTTPException(500, "Unable to deskew PDF.") from exc
