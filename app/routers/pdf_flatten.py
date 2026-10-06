"""HTTP layer for ``POST /api/v1/pdf/flatten``.

Responsibilities: request handling, upload validation (delegated to the
service), calling the service, building the response, mapping known
exceptions to HTTP errors and scheduling cleanup. No PDF logic lives here.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.services import pdf_flatten as service
from app.services.pdf_flatten import FlattenSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pdf", tags=["PDF"])

DOWNLOAD_FILENAME = "flattened-document.pdf"

# Order matters: subclasses must precede their parents.
_ERROR_STATUS: tuple[tuple[type[Exception], HTTPStatus], ...] = (
    (service.UnsupportedMediaTypeError, HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
    (service.FileTooLargeError, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (service.PDFValidationError, HTTPStatus.BAD_REQUEST),
    (service.PDFEncryptedError, HTTPStatus.UNPROCESSABLE_ENTITY),
    (service.PDFOpenError, HTTPStatus.UNPROCESSABLE_ENTITY),
    (service.PDFSignatureError, HTTPStatus.CONFLICT),
    (service.PDFTimeoutError, HTTPStatus.GATEWAY_TIMEOUT),
    (service.ResourceLimitError, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (service.PDFFlattenError, HTTPStatus.INTERNAL_SERVER_ERROR),
)


def _error_doc(description: str, example: str) -> dict[str, Any]:
    """OpenAPI documentation for a ``{"detail": "..."}`` error body (no schema model)."""
    return {
        "description": description,
        "content": {"application/json": {"example": {"detail": example}}},
    }


_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The flattened PDF.",
        "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        "headers": {
            "X-Flatten-Form-Fields": {"description": "Form fields found before flattening.",
                                      "schema": {"type": "integer"}},
            "X-Flatten-Annotations": {"description": "Annotations found before flattening.",
                                      "schema": {"type": "integer"}},
            "X-Signature-Invalidated": {"description": "Present (true) only if a signed PDF was "
                                        "flattened and its signature removed.",
                                        "schema": {"type": "string"}},
        },
    },
    400: _error_doc("Empty upload.", "The uploaded file is empty."),
    409: _error_doc("The PDF is digitally signed.",
                    "The PDF is digitally signed; flattening would invalidate the signature."),
    413: _error_doc("Upload or page count exceeds the configured limits.",
                    "The PDF exceeds the maximum allowed size of 50 MB."),
    415: _error_doc("Not a PDF (extension, MIME type or signature).",
                    "The uploaded file is not a valid PDF."),
    422: _error_doc("Corrupted, malformed or encrypted PDF.",
                    "Encrypted or password-protected PDFs are not supported."),
    500: _error_doc("Unexpected server error.", "Unable to flatten the uploaded PDF."),
    504: _error_doc("Flattening exceeded the time limit.",
                    "Flattening exceeded the allowed processing time."),
}


def get_flatten_settings() -> FlattenSettings:
    """FastAPI dependency; overridden in tests."""
    return FlattenSettings.from_config()


def _to_http_exception(exc: Exception) -> HTTPException:
    """Map service exceptions to HTTP errors.

    Service exceptions carry client-safe messages authored by us, so they are
    forwarded. Anything else is logged and replaced by a generic message.
    """
    for exc_type, status_code in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            return HTTPException(status_code=status_code.value, detail=str(exc))
    logger.exception("pdf_flatten.unexpected_error")
    return HTTPException(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
        detail="Unable to flatten the uploaded PDF.",
    )


@router.post(
    "/flatten",
    response_class=FileResponse,
    summary="Flatten a PDF",
    description=(
        "Flatten supported interactive PDF form fields and return a non-interactive PDF.\n\n"
        "* Text, checkbox, radio, dropdown and list fields become permanent page content.\n"
        "* Annotations that MuPDF can bake (highlights, free text, stamps, drawings, ...) "
        "are flattened too; link annotations are kept.\n"
        "* Text, vectors, images, page size and orientation are preserved: pages are "
        "**not** rasterised.\n"
        "* JavaScript, open/page actions and active link actions are always removed.\n"
        "* Digitally signed PDFs are rejected (409) because flattening invalidates "
        "signatures. Encrypted PDFs are rejected (422).\n"
        "* A PDF without form fields is returned unchanged in appearance (success)."
    ),
    responses=_RESPONSES,
)
def flatten_pdf_document(
    file: UploadFile = File(..., description="The PDF file (multipart/form-data)."),
    settings: FlattenSettings = Depends(get_flatten_settings),
) -> FileResponse:
    # A plain ``def`` endpoint: FastAPI runs it in the threadpool, which is
    # right for blocking file I/O and CPU-bound PyMuPDF calls.
    job: service.FlattenJob | None = None
    try:
        service.validate_upload_metadata(file.filename, file.content_type, file.size, settings)
        job = service.create_job(settings)
        service.save_upload(file.file, job, settings)
        result = service.flatten_pdf(job, settings)
    except Exception as exc:
        if job is not None:
            service.cleanup_job(job.root)
        raise _to_http_exception(exc) from exc

    headers = {
        "Cache-Control": "no-store",
        "X-Flatten-Form-Fields": str(result.form_fields),
        "X-Flatten-Annotations": str(result.annotations),
    }
    if result.was_signed:
        headers["X-Signature-Invalidated"] = "true"
    return FileResponse(
        path=result.output_path,
        media_type="application/pdf",
        filename=DOWNLOAD_FILENAME,
        headers=headers,
        background=BackgroundTask(service.cleanup_job, job.root),
    )