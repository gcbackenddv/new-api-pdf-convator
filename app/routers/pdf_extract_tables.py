"""HTTP layer for ``POST /api/v1/pdf/extract-tables``.

Request handling, option parsing, calling the service, response building and
exception-to-status mapping only. No extraction or export logic lives here.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.services.pdf_extract_tables import errors, service
from app.services.pdf_extract_tables.models import ImageFormat, OcrMode, OutputFormat
from app.services.pdf_extract_tables.ocr import OcrBackend, TesseractOcr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pdf", tags=["PDF"])

# Order matters: subclasses must precede their parents.
_ERROR_STATUS: tuple[tuple[type[Exception], HTTPStatus], ...] = (
    (errors.UnsupportedMediaTypeError, HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
    (errors.FileTooLargeError, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (errors.InvalidOptionsError, HTTPStatus.UNPROCESSABLE_ENTITY),
    (errors.PDFValidationError, HTTPStatus.BAD_REQUEST),
    (errors.NoTablesFoundError, HTTPStatus.NOT_FOUND),
    (errors.OCRUnavailableError, HTTPStatus.NOT_IMPLEMENTED),
    (errors.OCRProcessingError, HTTPStatus.INTERNAL_SERVER_ERROR),
    (errors.UnsupportedPDFError, HTTPStatus.UNPROCESSABLE_ENTITY),
    (errors.PDFExtractionError, HTTPStatus.UNPROCESSABLE_ENTITY),
    (errors.ExtractionTimeoutError, HTTPStatus.GATEWAY_TIMEOUT),
    (errors.ResourceLimitError, HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (errors.ExportError, HTTPStatus.INTERNAL_SERVER_ERROR),
    (errors.TableExtractionError, HTTPStatus.INTERNAL_SERVER_ERROR),
)


def _error_doc(description: str, example: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"example": {"detail": example}}},
    }


_BINARY = {"schema": {"type": "string", "format": "binary"}}
_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "The extracted tables. One file is returned directly (JSON, XLSX, HTML, "
            "Markdown, or a single CSV/image); several CSV files or images are returned "
            "as `extracted-tables.zip`."
        ),
        "content": {
            "application/json": {},
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": _BINARY,
            "text/csv": _BINARY,
            "text/html": _BINARY,
            "text/markdown": _BINARY,
            "image/png": _BINARY,
            "image/jpeg": _BINARY,
            "application/zip": _BINARY,
        },
        "headers": {
            "X-Table-Count": {"description": "Tables in the response.", "schema": {"type": "integer"}},
            "X-OCR-Pages": {"description": "Comma-separated pages that were OCR'd (omitted if none).",
                            "schema": {"type": "string"}},
            "X-Extraction-Warnings": {"description": "Number of non-fatal warnings (see JSON output).",
                                      "schema": {"type": "integer"}},
        },
    },
    400: _error_doc("Empty upload.", "The uploaded file is empty."),
    404: _error_doc("No tables detected, or table_index matches nothing.",
                    "No tables were detected in the uploaded PDF."),
    413: _error_doc("Upload or a configured limit exceeded.",
                    "The PDF exceeds the maximum allowed size of 50 MB."),
    415: _error_doc("Not a PDF (extension, MIME type or signature).",
                    "The uploaded file is not a valid PDF."),
    422: _error_doc("Corrupted or encrypted PDF, or invalid options.",
                    "Encrypted or password-protected PDFs are not supported."),
    500: _error_doc("Unexpected server error.", "Unable to extract tables from the uploaded PDF."),
    501: _error_doc("OCR is required but unavailable.",
                    "OCR is not available on this server."),
    504: _error_doc("Processing time limit exceeded.",
                    "Table extraction exceeded the allowed processing time."),
}


def get_table_settings() -> service.TableServiceSettings:
    """FastAPI dependency; overridden in tests."""
    return service.TableServiceSettings.from_config()


def get_ocr_backend() -> OcrBackend:
    """FastAPI dependency; overridden in tests."""
    return TesseractOcr()


def _to_http_exception(exc: Exception) -> HTTPException:
    """Service exceptions carry client-safe messages; anything else is generic."""
    for exc_type, status in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            return HTTPException(status_code=status.value, detail=str(exc))
    logger.exception("pdf_tables.unexpected_error")
    return HTTPException(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
        detail="Unable to extract tables from the uploaded PDF.",
    )


@router.post(
    "/extract-tables",
    response_class=FileResponse,
    summary="Extract tables from a PDF",
    description=(
        "Detects tables (bordered and borderless) in a PDF, normalizes them into one "
        "structured model and exports that model as JSON, CSV, XLSX, HTML, Markdown or "
        "an image.\n\n"
        "* **Scanned pages** are OCR'd only when they have no text layer (`ocr=auto`).\n"
        "* **Multi-page tables** are merged when `merge_tables=true` and the pages line up "
        "(consecutive pages, same columns, table at the bottom of one page and the top "
        "of the next). A repeated header row is dropped.\n"
        "* `table_index` selects tables after merging: `all`, `2`, or `1,3`.\n"
        "* CSV and image output return one file for one table, otherwise a ZIP.\n"
        "* Encrypted (password) PDFs are rejected."
    ),
    responses=_RESPONSES,
)
def extract_tables(
    file: UploadFile = File(..., description="The PDF file (multipart/form-data)."),
    output_format: OutputFormat = Query(OutputFormat.JSON, description="Export format."),
    image_format: ImageFormat = Query(ImageFormat.PNG, description="Used only when output_format=image."),
    page_start: int = Query(1, ge=1, description="First page to process (1-based)."),
    page_end: int | None = Query(None, ge=1, description="Last page to process (default: last page)."),
    table_index: str = Query("all", max_length=200,
                             description="`all`, a table number such as `2`, or a list such as `1,3`."),
    ocr: OcrMode = Query(OcrMode.AUTO, description="auto: OCR only pages without a text layer."),
    merge_tables: bool = Query(True, description="Merge tables continuing across pages."),
    settings: service.TableServiceSettings = Depends(get_table_settings),
    ocr_backend: OcrBackend = Depends(get_ocr_backend),
) -> FileResponse:
    # Plain ``def``: FastAPI runs it in the threadpool, which suits blocking file I/O,
    # PyMuPDF and OCR work.
    job: service.ExtractionJob | None = None
    try:
        options = service.RequestOptions(
            output_format=output_format, image_format=image_format, page_start=page_start,
            page_end=page_end, table_index=table_index, ocr=ocr, merge_tables=merge_tables,
        )
        service.validate_options(options)
        service.validate_upload_metadata(file.filename, file.content_type, file.size, settings)
        job = service.create_job(settings)
        service.save_upload(file.file, job, settings)
        result = service.process(job, settings, options, filename=file.filename, ocr_backend=ocr_backend)
    except Exception as exc:
        if job is not None:
            service.cleanup_job(job.root)
        raise _to_http_exception(exc) from exc

    out = result.file
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Table-Count": str(result.table_count),
        "X-Extraction-Warnings": str(result.warning_count),
    }
    if result.ocr_pages:
        headers["X-OCR-Pages"] = ",".join(str(p) for p in result.ocr_pages)
    if out.media_type.startswith("text/html"):
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return FileResponse(
        path=out.path,
        media_type=out.media_type,
        filename=out.filename,
        content_disposition_type="inline" if out.inline else "attachment",
        headers=headers,
        background=BackgroundTask(service.cleanup_job, job.root),
    )