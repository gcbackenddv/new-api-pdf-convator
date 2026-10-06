"""Orchestration: validate -> stream upload -> engine -> select -> export -> package.

Also owns the job-directory lifecycle (create, cleanup, stale sweep).
"""
from __future__ import annotations

import dataclasses
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.config import settings as config
from app.services.pdf_extract_tables.errors import (
    ExportError, FileTooLargeError, InvalidOptionsError, NoTablesFoundError, PDFValidationError,
    TableExtractionError, UnsupportedMediaTypeError,
)
from app.services.pdf_extract_tables.exporters import get_exporter
from app.services.pdf_extract_tables.exporters.base import ExportedFile, ExportSettings
from app.services.pdf_extract_tables.extractor import EngineSettings, ExtractionOptions, TableExtractionEngine
from app.services.pdf_extract_tables.models import ImageFormat, OcrMode, OutputFormat, TableDocument
from app.services.pdf_extract_tables.ocr import OcrBackend

logger = logging.getLogger(__name__)

MIB = 1024 * 1024
PDF_SIGNATURE = b"%PDF-"
PDF_SIGNATURE_WINDOW = 1024
UPLOAD_CHUNK_SIZE = MIB
INPUT_FILENAME = "input.pdf"
OUTPUT_DIRNAME = "output"
ZIP_FILENAME = "extracted-tables.zip"
ZIP_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_FILE_MODE = 0o644 << 16
MAX_SELECTED_TABLES = 1000
MAX_DISPLAY_NAME = 100

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DISPLAY_NAME_RE = re.compile(r"[^\w.\- \u0980-\u09ff\u200c\u200d]+")
_ACCEPTED_CONTENT_TYPES = frozenset({
    "application/pdf", "application/x-pdf", "application/acrobat",
    "text/pdf", "text/x-pdf", "application/octet-stream",
})


@dataclass(frozen=True)
class TableServiceSettings:
    output_root: Path
    max_pdf_bytes: int
    job_ttl_seconds: int
    engine: EngineSettings
    export: ExportSettings

    @classmethod
    def from_config(cls) -> "TableServiceSettings":
        return cls(
            output_root=config.OUTPUT_DIR / config.PDF_TABLES_DIRNAME,
            max_pdf_bytes=config.MAX_PDF_SIZE_MB * MIB,
            job_ttl_seconds=config.PDF_TABLES_JOB_TTL_SECONDS,
            engine=EngineSettings(
                max_pages=config.MAX_PDF_PAGES,
                max_tables=config.MAX_TABLES,
                max_rows_per_table=config.MAX_ROWS_PER_TABLE,
                max_columns_per_table=config.MAX_COLUMNS_PER_TABLE,
                max_page_dimension_pt=config.TABLE_MAX_PAGE_DIMENSION_PT,
                timeout_seconds=config.TABLE_EXTRACTION_TIMEOUT,
                borderless=config.TABLE_BORDERLESS_DETECTION,
                ocr_enabled=config.OCR_ENABLED,
                ocr_language=config.OCR_LANGUAGE,
                ocr_timeout_seconds=config.OCR_TIMEOUT,
                ocr_dpi=config.OCR_DPI,
                ocr_max_pages=config.OCR_MAX_PAGES,
                ocr_max_pixels=config.OCR_MAX_PIXELS,
                ocr_min_words=config.OCR_MIN_WORDS,
                continuation_edge_ratio=config.TABLE_CONTINUATION_EDGE_RATIO,
                column_align_tolerance=config.TABLE_COLUMN_ALIGN_TOLERANCE,
            ),
            export=ExportSettings(
                csv_bom=config.TABLE_CSV_BOM,
                image_max_rows=config.TABLE_IMAGE_MAX_ROWS,
                image_max_pixels=config.TABLE_IMAGE_MAX_PIXELS,
                latin_font_path=config.TABLE_IMAGE_FONT_PATH,
                bengali_font_path=config.TABLE_IMAGE_BENGALI_FONT_PATH,
            ),
        )


@dataclass(frozen=True)
class RequestOptions:
    output_format: OutputFormat = OutputFormat.JSON
    image_format: ImageFormat = ImageFormat.PNG
    page_start: int = 1
    page_end: int | None = None
    table_index: str = "all"
    ocr: OcrMode = OcrMode.AUTO
    merge_tables: bool = True


@dataclass(frozen=True)
class ExtractionJob:
    root: Path

    @property
    def job_id(self) -> str:
        return self.root.name

    @property
    def input_path(self) -> Path:
        return self.root / INPUT_FILENAME

    @property
    def output_dir(self) -> Path:
        return self.root / OUTPUT_DIRNAME


@dataclass(frozen=True)
class ProcessResult:
    file: ExportedFile
    table_count: int
    ocr_pages: tuple[int, ...]
    warning_count: int


# ------------------------------------------------------------------ logging
def _log(level: int, event: str, **fields: object) -> None:
    """Key=value logging. Never pass document text, table cells or filenames."""
    logger.log(level, "%s %s", event, " ".join(f"{k}={v}" for k, v in fields.items()))


# ------------------------------------------------------------------ validation
def parse_table_selection(value: str | None) -> frozenset[int] | None:
    text = (value or "all").strip().lower()
    if text in ("", "all"):
        return None
    try:
        numbers = frozenset(int(part) for part in text.split(","))
    except ValueError:
        numbers = frozenset()
    if not numbers or min(numbers) < 1 or len(numbers) > MAX_SELECTED_TABLES:
        raise InvalidOptionsError("table_index must be 'all', a table number, or a comma-separated list of numbers.")
    return numbers


def validate_options(options: RequestOptions) -> frozenset[int] | None:
    """Cheap checks done before any upload is processed."""
    if options.page_end is not None and options.page_end < options.page_start:
        raise InvalidOptionsError("page_end must be greater than or equal to page_start.")
    return parse_table_selection(options.table_index)


def validate_upload_metadata(filename: str | None, content_type: str | None, size: int | None,
                             settings: TableServiceSettings) -> None:
    """The filename is used only for its extension, never for any path."""
    if Path(filename or "").suffix.lower() != ".pdf":
        raise UnsupportedMediaTypeError("Only files with a .pdf extension are accepted.")
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime and mime not in _ACCEPTED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError("The uploaded file is not declared as a PDF.")
    if size is not None and size > settings.max_pdf_bytes:
        raise FileTooLargeError(_too_large_message(settings))


def _too_large_message(settings: TableServiceSettings) -> str:
    return f"The PDF exceeds the maximum allowed size of {settings.max_pdf_bytes / MIB:.0f} MB."


def sanitize_display_name(name: str | None) -> str:
    """Metadata only (JSON/HTML). Strips directories and unsafe characters."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _DISPLAY_NAME_RE.sub("_", base).strip(" .")[:MAX_DISPLAY_NAME]
    return base or "document.pdf"


# ------------------------------------------------------------------ job lifecycle
def create_job(settings: TableServiceSettings) -> ExtractionJob:
    purge_stale_jobs(settings)
    root = settings.output_root / uuid.uuid4().hex
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    (root / OUTPUT_DIRNAME).mkdir(mode=0o700)
    return ExtractionJob(root=root)


def cleanup_job(job_root: Path) -> None:
    """Remove a job directory. Refuses anything that isn't a UUID-named directory."""
    if not _JOB_ID_RE.match(job_root.name):
        _log(logging.ERROR, "pdf_tables.cleanup_refused", reason="unexpected_name")
        return
    try:
        shutil.rmtree(job_root)
        _log(logging.INFO, "pdf_tables.cleaned", job_id=job_root.name)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("pdf_tables.cleanup_failed job_id=%s", job_root.name)


def purge_stale_jobs(settings: TableServiceSettings) -> None:
    """Safety net for jobs orphaned by crashes or client disconnects."""
    try:
        entries = list(settings.output_root.iterdir())
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("pdf_tables.purge_failed")
        return
    cutoff = time.time() - settings.job_ttl_seconds
    for entry in entries:
        try:
            if _JOB_ID_RE.match(entry.name) and entry.is_dir() and entry.stat().st_mtime < cutoff:
                cleanup_job(entry)
        except OSError:
            logger.exception("pdf_tables.purge_entry_failed")


def save_upload(stream: BinaryIO, job: ExtractionJob, settings: TableServiceSettings) -> int:
    """Stream the upload to disk, enforcing signature and size limits."""
    total = 0
    checked_signature = False
    fd = os.open(job.input_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        while chunk := stream.read(UPLOAD_CHUNK_SIZE):
            if not checked_signature:
                if PDF_SIGNATURE not in chunk[:PDF_SIGNATURE_WINDOW]:
                    raise UnsupportedMediaTypeError("The uploaded file is not a valid PDF.")
                checked_signature = True
            total += len(chunk)
            if total > settings.max_pdf_bytes:
                raise FileTooLargeError(_too_large_message(settings))
            out.write(chunk)
    if total == 0:
        raise PDFValidationError("The uploaded file is empty.")
    _log(logging.INFO, "pdf_tables.validated", job_id=job.job_id, size_bytes=total)
    return total


# ------------------------------------------------------------------ processing
def process(job: ExtractionJob, settings: TableServiceSettings, options: RequestOptions,
            *, filename: str | None, ocr_backend: OcrBackend | None = None) -> ProcessResult:
    selection = validate_options(options)
    started = time.monotonic()
    _log(logging.INFO, "pdf_tables.started", job_id=job.job_id, output_format=options.output_format.value)
    engine = TableExtractionEngine(settings.engine, ocr_backend=ocr_backend)
    try:
        document = engine.extract(
            job.input_path, filename=sanitize_display_name(filename),
            options=ExtractionOptions(options.page_start, options.page_end, options.ocr, options.merge_tables),
        )
    except TableExtractionError:
        _log(logging.WARNING, "pdf_tables.failed", job_id=job.job_id)
        raise
    except Exception as exc:
        logger.error("pdf_tables.failed job_id=%s error_type=%s", job.job_id, type(exc).__name__, exc_info=True)
        raise TableExtractionError("Unable to extract tables from the uploaded PDF.") from exc
    finally:
        job.input_path.unlink(missing_ok=True)       # the upload is no longer needed

    document = _select_tables(document, selection)
    files = _export(document, job, settings, options)
    result_file = files[0] if len(files) == 1 else _zip_files(files, job)
    _log(logging.INFO, "pdf_tables.completed", job_id=job.job_id, tables=len(document.tables),
         ocr_pages=len(document.ocr_pages), files=len(files), seconds=f"{time.monotonic() - started:.2f}")
    return ProcessResult(result_file, len(document.tables), document.ocr_pages, len(document.warnings))


def _select_tables(document: TableDocument, selection: frozenset[int] | None) -> TableDocument:
    if selection is None:
        return document
    chosen = tuple(t for t in document.tables if t.number in selection)
    if not chosen:
        raise NoTablesFoundError("The requested table_index does not match any detected table.")
    return dataclasses.replace(document, tables=chosen)


def _export(document: TableDocument, job: ExtractionJob, settings: TableServiceSettings,
            options: RequestOptions) -> list[ExportedFile]:
    export_settings = dataclasses.replace(settings.export, image_format=options.image_format)
    try:
        files = get_exporter(options.output_format, export_settings).export(document, job.output_dir)
    except TableExtractionError:
        raise
    except Exception as exc:
        logger.error("pdf_tables.export_failed job_id=%s error_type=%s", job.job_id, type(exc).__name__, exc_info=True)
        raise ExportError("Unable to export the extracted tables.") from exc
    if not files:
        raise ExportError("Unable to export the extracted tables.")
    return files


def _zip_files(files: list[ExportedFile], job: ExtractionJob) -> ExportedFile:
    """Package generated files; archive entries are bare, generated filenames."""
    zip_path = job.output_dir / ZIP_FILENAME
    with zipfile.ZipFile(zip_path, mode="x") as archive:
        for exported in sorted(files, key=lambda f: f.filename):
            if Path(exported.filename).name != exported.filename:
                raise ExportError("Unable to export the extracted tables.")
            info = zipfile.ZipInfo(exported.filename, date_time=ZIP_FIXED_TIMESTAMP)
            info.external_attr = ZIP_FILE_MODE
            info.compress_type = zipfile.ZIP_STORED if exported.media_type.startswith("image/") else zipfile.ZIP_DEFLATED
            with open(exported.path, "rb") as src, archive.open(info, "w") as dst:
                shutil.copyfileobj(src, dst, MIB)
    return ExportedFile(path=zip_path, filename=ZIP_FILENAME, media_type="application/zip")