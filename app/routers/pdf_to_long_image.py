import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.output import safe_stem, save_output
from app.services.pdf_to_long_image import (
    LongImageError,
    convert_pdf_to_long_image,
    resolve_format,
)

router = APIRouter(prefix="/convert", tags=["convert"])
CHUNK = 1024 * 1024


@router.post("/pdf-to-long-image")
def pdf_to_long_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    output_format: str = Query("png", alias="format"), # default to png if not specified
    dpi: int = Query(settings.LONG_IMAGE_DPI, ge=72, le=300),
    quality: int = Query(settings.LONG_IMAGE_QUALITY, ge=1, le=100),
):
    try:
        fmt = resolve_format(output_format)
    except LongImageError as exc:
        raise HTTPException(exc.status_code, exc.message)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file.")

    work_dir = Path(tempfile.mkdtemp(prefix="pdf2long_"))
    keep = False
    try:
        pdf_path = work_dir / "input.pdf"  # client filename is never used for paths
        limit = settings.MAX_PDF_SIZE_MB * 1024 * 1024
        written = 0
        with pdf_path.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, f"File exceeds {settings.MAX_PDF_SIZE_MB} MB.")
                out.write(chunk)
        if written == 0:
            raise HTTPException(400, "The uploaded file is empty.")

        try:
            result = convert_pdf_to_long_image(
                pdf_path, work_dir, fmt,
                dpi=dpi,
                quality=quality,
                max_pages=settings.LONG_IMAGE_MAX_PAGES,
                max_pixels=settings.LONG_IMAGE_MAX_PIXELS,
                max_dimension=settings.LONG_IMAGE_MAX_DIMENSION,
            )
        except LongImageError as exc:
            raise HTTPException(exc.status_code, exc.message)

        pdf_path.unlink(missing_ok=True)
        out_name = f"{safe_stem(file.filename)}_converted.{fmt.extension}"
        save_output(result.path, out_name)
        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        keep = True
        return FileResponse(
            result.path,
            media_type=fmt.media_type,
            filename=out_name,
        )
    finally:
        if not keep:
            shutil.rmtree(work_dir, ignore_errors=True)


