import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.output import safe_stem, save_output
from app.services.pdf_to_heic import PdfToHeicError, convert_pdf_to_heic_zip

router = APIRouter(prefix="/convert", tags=["convert"])
CHUNK = 1024 * 1024


@router.post("/pdf-to-heic")
def pdf_to_heic(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    dpi: int = Query(settings.DEFAULT_PDF_DPI, ge=72, le=400),
    quality: int = Query(settings.DEFAULT_HEIC_QUALITY, ge=1, le=100),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file.")

    work_dir = Path(tempfile.mkdtemp(prefix="pdf2heic_"))
    keep = False
    try:
        pdf_path = work_dir / "input.pdf"  # never use the client's filename
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
            result = convert_pdf_to_heic_zip(
                pdf_path, work_dir,
                dpi=dpi, quality=quality, max_pages=settings.MAX_PDF_PAGES,
            )
        except PdfToHeicError as exc:
            raise HTTPException(exc.status_code, exc.message)

        out_name = f"{safe_stem(file.filename)}_converted.zip"
        pdf_path.unlink(missing_ok=True)
        save_output(result.zip_path, out_name)
        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        keep = True
        return FileResponse(
            result.zip_path,
            media_type="application/zip",
            filename=out_name,
        )
    finally:
        if not keep:
            shutil.rmtree(work_dir, ignore_errors=True)