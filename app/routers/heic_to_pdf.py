import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.output import safe_stem, save_output
from app.services.heic_to_pdf import HeicToPdfError, convert_heic_to_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/convert", tags=["convert"])
CHUNK = 1024 * 1024
ALLOWED_EXT = (".heic", ".heif")


def _natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


@router.post(
    "/heic-to-pdf",
    summary="Convert one or more HEIC/HEIF images to a single PDF",
    description=(
        "Upload one or more `.heic` / `.heif` files as repeated `files` form fields. "
        "Each image becomes one PDF page, in upload order unless `sort=name`. "
        "EXIF orientation is applied. Limits are set by environment variables "
        "(`MAX_HEIC_FILES`, `MAX_HEIC_FILE_SIZE_MB`, `MAX_TOTAL_UPLOAD_SIZE_MB`, `MAX_IMAGE_PIXELS`). "
        "One file returns `<name>_converted.pdf`; several return `converted_images_converted.pdf`."
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The generated PDF."},
        400: {"description": "No files, unsupported file type, empty file."},
        413: {"description": "File, total upload, file count or image resolution limit exceeded."},
        422: {"description": "A HEIC image could not be decoded."},
        500: {"description": "Unable to generate PDF."},
    },
)
def heic_to_pdf(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(None, description="One or more .heic/.heif files"),
    page_size: Literal["auto", "a4", "letter"] = Query(
        "auto", description="auto = page matches the image; a4/letter = image fitted and centered"
    ),
    sort: Literal["false", "name"] = Query(
        "false", description="false = keep upload order; name = natural sort by filename"
    ),
    compression: Literal["jpeg", "lossless"] = Query(
        "jpeg", description="jpeg = smaller PDF; lossless = PNG, exact pixels, larger PDF"
    ),
    dpi: int = Query(settings.HEIC_PDF_DPI, ge=72, le=600, description="Used by page_size=auto"),
    quality: int = Query(settings.HEIC_PDF_QUALITY, ge=1, le=100, description="JPEG quality"),
):
    uploads = [f for f in (files or []) if f.filename]  # browsers may send empty parts
    if not uploads:
        raise HTTPException(400, "No HEIC files were uploaded.")
    if len(uploads) > settings.MAX_HEIC_FILES:
        raise HTTPException(413, "Maximum number of HEIC files exceeded.")

    entries = []
    for upload in uploads:
        if not upload.filename.lower().endswith(ALLOWED_EXT):
            raise HTTPException(400, "Only HEIC/HEIF files are supported.")
        entries.append((upload, safe_stem(upload.filename, "image")))
    if sort == "name":
        entries.sort(key=lambda e: _natural_key(e[1]))

    work_dir = Path(tempfile.mkdtemp(prefix="heic2pdf_"))
    keep = False
    try:
        per_file_limit = settings.MAX_HEIC_FILE_SIZE_MB * 1024 * 1024
        total_limit = settings.MAX_TOTAL_UPLOAD_SIZE_MB * 1024 * 1024
        total = 0
        items: list[tuple[Path, str]] = []
        for i, (upload, stem) in enumerate(entries, start=1):
            dest = work_dir / f"input-{i:03d}.heic"  # client filename is never a path
            written = 0
            with dest.open("wb") as out:
                while chunk := upload.file.read(CHUNK):
                    written += len(chunk)
                    total += len(chunk)
                    if written > per_file_limit:
                        raise HTTPException(413, "File exceeds the maximum allowed size.")
                    if total > total_limit:
                        raise HTTPException(413, "Total upload exceeds the maximum allowed size.")
                    out.write(chunk)
            if written == 0:
                raise HTTPException(400, f"Empty file: {stem}")
            items.append((dest, f"{stem}.heic"))

        try:
            result = convert_heic_to_pdf(
                items, work_dir,
                dpi=dpi, quality=quality, page_size=page_size,
                compression=compression, max_pixels=settings.MAX_IMAGE_PIXELS,
            )
        except HeicToPdfError as exc:
            raise HTTPException(exc.status_code, exc.message)
        except Exception:
            logger.exception("Unexpected HEIC to PDF failure")
            raise HTTPException(500, "Unable to generate PDF.")

        out_name = (
            f"{entries[0][1]}_converted.pdf"
            if len(entries) == 1
            else "converted_images_converted.pdf"
        )
        save_output(result.pdf_path, out_name)
        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        keep = True
        return FileResponse(result.pdf_path, media_type="application/pdf", filename=out_name)
    finally:
        if not keep:
            shutil.rmtree(work_dir, ignore_errors=True)