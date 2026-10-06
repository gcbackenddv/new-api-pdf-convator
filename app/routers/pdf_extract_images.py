"""HTTP layer for ``POST /api/v1/pdf/extract-images``.

Responsibilities: request handling, upload validation (delegated to the
service), calling the service, building the response and mapping known
exceptions to HTTP errors. No extraction logic lives here.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.services import pdf_extract_images as service
from app.services.pdf_extract_images import ExtractionSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pdf", tags=["PDF"])

DOWNLOAD_FILENAME = "extracted-images.zip"

# Order matters: subclasses must precede their parents.
_ERROR_STATUS: tuple[tuple[type[Exception], HTTPStatus], ...] = (
    (service.UnsupportedMediaTypeError, HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
    (service.FileTooLargeError, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (service.PDFValidationError, HTTPStatus.BAD_REQUEST),
    (service.NoImagesFoundError, HTTPStatus.NOT_FOUND),
    (service.UnsupportedPDFError, HTTPStatus.UNPROCESSABLE_ENTITY),
    (service.ExtractionTimeoutError, HTTPStatus.GATEWAY_TIMEOUT),
    (service.ResourceLimitError, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (service.OutputFormatUnavailableError, HTTPStatus.NOT_IMPLEMENTED),
    (service.PDFExtractionError, HTTPStatus.UNPROCESSABLE_ENTITY),
)


def _error_doc(description: str, example: str) -> dict[str, Any]:
    """OpenAPI documentation for a ``{"detail": "..."}`` error body (no schema model)."""
    return {
        "description": description,
        "content": {"application/json": {"example": {"detail": example}}},
    }


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "ZIP archive of the extracted images.",
        "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
    },
    400: _error_doc("Empty upload.", "The uploaded file is empty."),
    404: _error_doc("The PDF contains no embedded images.",
                    "No embedded images were found in the PDF."),
    413: _error_doc("Upload or extracted output exceeds the configured limits.",
                    "The PDF exceeds the maximum allowed size of 50 MB."),
    415: _error_doc("Not a PDF (extension, MIME type or signature).",
                    "The uploaded file is not a valid PDF."),
    422: _error_doc("Corrupted, encrypted or otherwise unsupported PDF, or invalid form value.",
                    "Password-protected PDFs are not supported."),
    500: _error_doc("Unexpected server error.",
                    "Unable to extract images from the uploaded PDF."),
    501: _error_doc("The requested output format is unavailable on this server.",
                    "HEIC output is not available on this server."),
    504: _error_doc("Extraction exceeded the time limit.",
                    "Image extraction exceeded the allowed processing time."),
}


def get_extraction_settings() -> ExtractionSettings:
    """FastAPI dependency; overridden in tests."""
    return ExtractionSettings.from_config()


def _to_http_exception(exc: Exception) -> HTTPException:
    """Map service exceptions to HTTP errors.

    Service exceptions carry client-safe messages authored by us, so they are
    forwarded. Anything else is logged and replaced by a generic message.
    """
    for exc_type, status_code in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            return HTTPException(status_code=status_code.value, detail=str(exc))
    logger.exception("pdf_image_extraction.unexpected_error")
    return HTTPException(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
        detail="Unable to extract images from the uploaded PDF.",
    )


@router.post(
    "/extract-images",
    response_class=FileResponse,
    summary="Extract all embedded images from a PDF as a ZIP",
    description=(
        "Uploads a PDF and returns a ZIP archive containing the **original "
        "embedded raster images** (not page screenshots) under `images/`.\n\n"
        "* Files are named `page-NNN-image-NNN.<ext>`.\n"
        "* An image object reused on several pages is extracted **once**, "
        "under the first page that uses it.\n"
        "* `output_format` selects the image format: `original` (default, "
        "original bytes kept where possible), `jpg`/`jpeg`, `png`, `webp` or "
        "`heic`. Images already in the requested format are not re-encoded. "
        "Transparency is flattened onto white for JPEG.\n"
        "* Images with a soft mask are exported with transparency where the "
        "target format supports it.\n"
        "* Password-protected PDFs are rejected."
    ),
    responses=_RESPONSES,
)
def extract_images(
    file: UploadFile = File(..., description="The PDF file (multipart/form-data)."),
    output_format: service.OutputFormat = Form(
        service.OutputFormat.ORIGINAL,
        description="Image format inside the ZIP: original, jpg, jpeg, png, webp or heic.",
    ),
    settings: ExtractionSettings = Depends(get_extraction_settings),
) -> FileResponse:
    # A plain ``def`` endpoint: FastAPI runs it in the threadpool, which is
    # right for blocking file I/O and CPU-bound PyMuPDF/Pillow calls.
    job: service.ExtractionJob | None = None
    try:
        service.validate_output_format(output_format)
        service.validate_upload_metadata(file.filename, file.content_type, file.size, settings)
        job = service.create_job(settings)
        service.save_upload(file.file, job, settings)
        result = service.extract_images_to_zip(job, settings, output_format)
    except Exception as exc:
        if job is not None:
            service.cleanup_job(job.root)
        raise _to_http_exception(exc) from exc

    return FileResponse(
        path=result.zip_path,
        media_type="application/zip",
        filename=DOWNLOAD_FILENAME,
        headers={
            "Cache-Control": "no-store",
            "X-Extracted-Image-Count": str(result.images_extracted),
            "X-Output-Format": output_format.value,
        },
        background=BackgroundTask(service.cleanup_job, job.root),
    )