import logging
import re
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.services.pptx_to_pdf import (
    ALLOWED_EXTENSIONS, TEMP_PREFIX, PptxToPdfError,
    convert_presentation_to_pdf, find_soffice,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/convert", tags=["convert"])
CHUNK = 1024 * 1024
_slots = threading.BoundedSemaphore(settings.PPTX_PDF_MAX_CONCURRENT)  # per worker process
_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _safe_stem(raw: str) -> str:
    base = Path(raw.replace("\\", "/")).name
    return re.sub(r"[^\w.\- ]", "_", Path(base).stem)[:80].strip("._ ") or "converted"


@router.get("/pptx-to-pdf/health", summary="Is the conversion engine available?")
def pptx_to_pdf_health():
    if find_soffice(settings.PPTX_PDF_SOFFICE_PATH) is None:
        raise HTTPException(503, "The PowerPoint conversion engine is not available.")
    return {"available": True}


@router.post(
    "/pptx-to-pdf",
    summary="Convert a PowerPoint (.ppt or .pptx) file to PDF",
    description=(
        "Each slide becomes one PDF page. Rendering is done by LibreOffice, which must be "
        "installed on the server. Presentations with externally linked content are rejected. "
        "Limits: `PPTX_PDF_MAX_FILE_MB`, `PPTX_PDF_MAX_SLIDES`, `PPTX_PDF_TIMEOUT_SECONDS`."
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The generated PDF."},
        400: {"description": "No file, wrong type, empty, invalid or unsafe presentation."},
        413: {"description": "File size, slide count or complexity limit exceeded."},
        422: {"description": "LibreOffice could not load the presentation."},
        500: {"description": "Presentation conversion failed."},
        503: {"description": "Engine unavailable or server busy."},
        504: {"description": "Conversion timed out."},
    },
)
def pptx_to_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None, description="A .ppt or .pptx file"),
):
    if file is None or not file.filename:
        raise HTTPException(400, "No presentation file was uploaded.")
    extension = Path(file.filename.replace("\\", "/")).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Only .ppt and .pptx files are supported.")

    job_id = uuid.uuid4().hex[:8]
    work_dir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))  # random name, owner-only
    keep = False
    try:
        input_path = work_dir / f"input{extension}"  # extension comes from a whitelist
        limit = settings.PPTX_PDF_MAX_FILE_MB * 1024 * 1024
        written = 0
        with input_path.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, "The file exceeds the maximum allowed size.")
                out.write(chunk)
        if written == 0:
            raise HTTPException(400, "The uploaded file is empty.")

        if not _slots.acquire(timeout=settings.PPTX_PDF_QUEUE_WAIT_SECONDS):
            logger.warning("[%s] Rejected: all conversion slots busy", job_id)
            raise HTTPException(503, "The server is busy. Please try again shortly.")
        try:
            result = convert_presentation_to_pdf(
                input_path, work_dir,
                job_id=job_id,
                soffice_path=settings.PPTX_PDF_SOFFICE_PATH,
                timeout=settings.PPTX_PDF_TIMEOUT_SECONDS,
                max_slides=settings.PPTX_PDF_MAX_SLIDES,
                max_uncompressed_bytes=settings.PPTX_PDF_MAX_UNCOMPRESSED_MB * 1024 * 1024,
                max_entries=settings.PPTX_PDF_MAX_ZIP_ENTRIES,
                max_output_bytes=settings.PPTX_PDF_MAX_OUTPUT_MB * 1024 * 1024,
            )
        except PptxToPdfError as exc:
            raise HTTPException(exc.status_code, exc.message)
        except Exception:
            logger.exception("[%s] Unexpected conversion failure", job_id)
            raise HTTPException(500, "Presentation conversion failed.")
        finally:
            _slots.release()

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        keep = True
        return FileResponse(
            result.pdf_path,
            media_type="application/pdf",
            filename=f"{_safe_stem(file.filename)}.pdf",
            headers=_HEADERS,
        )
    finally:
        if not keep:
            shutil.rmtree(work_dir, ignore_errors=True)