import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.output import safe_stem, save_output
from app.services.pdf_to_pptx import PdfToPptxError, convert_pdf_to_pptx

logger = logging.getLogger(__name__)
router = APIRouter(tags=["convert"])
CHUNK = 1024 * 1024
PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _handle_pdf_to_pptx_conversion(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    dpi: int,
    ocr: bool,
) -> FileResponse:
    if file is None or not file.filename:
        raise HTTPException(400, "No PDF file was uploaded.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    unique_id = uuid.uuid4().hex[:8]
    work_dir = Path(tempfile.mkdtemp(prefix=f"pdf2pptx_{unique_id}_"))
    keep = False
    try:
        pdf_path = work_dir / "input.pdf"  # Client filename is never used for filesystem paths
        limit = settings.PPTX_MAX_PDF_SIZE_MB * 1024 * 1024
        written = 0
        with pdf_path.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, "PDF exceeds the maximum allowed file size.")
                out.write(chunk)
        if written == 0:
            raise HTTPException(400, "The uploaded file is empty.")

        try:
            result = convert_pdf_to_pptx(
                pdf_path,
                work_dir / "converted.pptx",
                dpi=dpi,
                max_pages=settings.PPTX_MAX_PAGES,
                max_pixels=settings.PPTX_MAX_PIXELS_PER_PAGE,
                image_format=settings.PPTX_IMAGE_FORMAT,
                jpeg_quality=settings.PPTX_JPEG_QUALITY,
                default_font=settings.PDF_TO_PPTX_DEFAULT_FONT,
                ocr_enabled=ocr,
                ocr_languages=settings.PDF_TO_PPTX_OCR_LANGUAGES,
                extract_images=settings.PDF_TO_PPTX_EXTRACT_IMAGES,
                extract_shapes=settings.PDF_TO_PPTX_EXTRACT_SHAPES,
                detect_tables=settings.PDF_TO_PPTX_DETECT_TABLES,
            )
        except PdfToPptxError as exc:
            raise HTTPException(exc.status_code, exc.message)
        except Exception:
            logger.exception("Unexpected PDF to PPTX conversion failure")
            raise HTTPException(500, "Unable to convert PDF to PowerPoint.")

        out_name = f"{safe_stem(file.filename)}_converted.pptx"
        save_output(result.output_path, out_name)
        pdf_path.unlink(missing_ok=True)
        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        keep = True
        headers = {}
        if hasattr(result, "slide_count"):
            headers["X-Slide-Count"] = str(result.slide_count)
        if hasattr(result, "size_bytes"):
            headers["X-Output-Size"] = str(result.size_bytes)
        return FileResponse(
            result.output_path,
            media_type=PPTX_MEDIA_TYPE,
            filename=out_name,
            headers=headers or None,
        )
    finally:
        if not keep:
            shutil.rmtree(work_dir, ignore_errors=True)


@router.post(
    "/convert/pdf-to-pptx",
    summary="Convert a PDF to an editable PowerPoint presentation",
    description=(
        "Converts PDF documents into editable PowerPoint slides. Extracted elements include "
        "editable text boxes (with fonts, sizes, colors, and styles preserved), separate images, "
        "native vector shapes, and reconstructed tables with proper z-order stacking."
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {PPTX_MEDIA_TYPE: {}}, "description": "The generated editable PPTX."},
        400: {"description": "No file, wrong file type, empty or invalid PDF."},
        413: {"description": "File size or page count limit exceeded."},
        422: {"description": "The PDF is corrupted and cannot be rendered."},
        500: {"description": "Unable to convert PDF to PowerPoint."},
    },
)
def pdf_to_pptx(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None, description="A PDF file"),
    dpi: int = Query(settings.PPTX_RENDER_DPI, ge=0, le=600, description="Render resolution (0 or omit for automatic optimal DPI)"),
    ocr: bool = Query(settings.PDF_TO_PPTX_OCR_ENABLED, description="Enable OCR for scanned pages"),
):
    return _handle_pdf_to_pptx_conversion(background_tasks, file, dpi, ocr)


@router.post(
    "/api/v1/pdf-to-pptx",
    summary="Convert a PDF to an editable PowerPoint presentation (v1 API)",
    description="Alias route for PDF to editable PPTX conversion.",
    response_class=FileResponse,
    responses={
        200: {"content": {PPTX_MEDIA_TYPE: {}}, "description": "The generated editable PPTX."},
        400: {"description": "No file, wrong file type, empty or invalid PDF."},
        413: {"description": "File size or page count limit exceeded."},
        500: {"description": "Unable to convert PDF to PowerPoint."},
    },
)
def pdf_to_pptx_v1(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None, description="A PDF file"),
    dpi: int = Query(settings.PPTX_RENDER_DPI, ge=0, le=600, description="Render resolution (0 or omit for automatic optimal DPI)"),
    ocr: bool = Query(settings.PDF_TO_PPTX_OCR_ENABLED, description="Enable OCR for scanned pages"),
):
    return _handle_pdf_to_pptx_conversion(background_tasks, file, dpi, ocr)