"""Table extraction engine: PDF -> analysis -> detection -> normalization -> TableDocument.

Knows nothing about uploads, HTTP or export formats.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.services.pdf_extract_tables.detector import LatticeDetector, StreamDetector, read_words
from app.services.pdf_extract_tables.errors import (
    ExtractionTimeoutError, InvalidOptionsError, NoTablesFoundError, OCRProcessingError,
    OCRUnavailableError, PDFExtractionError, ResourceLimitError, TableTooLargeError,
    UnsupportedPDFError,
)
from app.services.pdf_extract_tables.models import (
    OcrMode, RawTable, Table, TableDocument, bbox_overlap_ratio,
)
from app.services.pdf_extract_tables.normalizer import build_table, merge_continuations
from app.services.pdf_extract_tables.ocr import OcrBackend, TesseractOcr, effective_dpi

logger = logging.getLogger(__name__)

DUPLICATE_OVERLAP = 0.5          # stream table dropped if it overlaps a lattice table this much
MAX_LISTED_PAGES = 10


@dataclass(frozen=True, slots=True)
class EngineSettings:
    max_pages: int = 500
    max_tables: int = 500
    max_rows_per_table: int = 5000
    max_columns_per_table: int = 50
    max_page_dimension_pt: float = 14400
    timeout_seconds: float = 120
    borderless: bool = True
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    ocr_timeout_seconds: float = 120
    ocr_dpi: int = 200
    ocr_max_pages: int = 30
    ocr_max_pixels: int = 40_000_000
    ocr_min_words: int = 5
    continuation_edge_ratio: float = 0.25
    column_align_tolerance: float = 0.02


@dataclass(frozen=True, slots=True)
class ExtractionOptions:
    page_start: int = 1
    page_end: int | None = None
    ocr: OcrMode = OcrMode.AUTO
    merge_tables: bool = True


class _Deadline:
    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() > self._end:
            raise ExtractionTimeoutError("Table extraction exceeded the allowed processing time.")


class _RunState:
    def __init__(self) -> None:
        self.ocr_pages: list[int] = []
        self.ocr_skipped: list[int] = []
        self.ocr_seconds = 0.0
        self.warnings: list[str] = []


class TableExtractionEngine:
    def __init__(self, settings: EngineSettings, *, ocr_backend: OcrBackend | None = None) -> None:
        self._s = settings
        self._ocr = ocr_backend or TesseractOcr()
        self._lattice = LatticeDetector()
        self._stream = StreamDetector()
        self._ocr_ready: bool | None = None

    # ------------------------------------------------------------------ public
    def extract(self, pdf_path: Path, *, filename: str, options: ExtractionOptions) -> TableDocument:
        s = self._s
        deadline = _Deadline(s.timeout_seconds)
        with self._open(pdf_path) as doc:
            page_count = doc.page_count
            first, last = self._resolve_range(page_count, options)
            logger.info("pdf_tables.analysis pages=%d range=%d-%d ocr=%s",
                        page_count, first, last, options.ocr.value)
            if options.ocr is OcrMode.TRUE:
                self._require_ocr(last - first + 1)

            state = _RunState()
            tables: list[Table] = []
            for page_no in range(first, last + 1):
                deadline.check()
                tables.extend(self._process_page(doc.load_page(page_no - 1), page_no, options, state))
                if len(tables) > s.max_tables:
                    raise ResourceLimitError(f"The PDF contains more than {s.max_tables} tables.")

        if options.merge_tables:
            tables = merge_continuations(
                tables, edge_ratio=s.continuation_edge_ratio,
                align_tolerance=s.column_align_tolerance, max_rows=s.max_rows_per_table,
            )
        tables = [dataclasses.replace(t, number=i) for i, t in enumerate(tables, 1)]

        if not tables:
            if state.ocr_skipped:
                raise OCRUnavailableError(
                    "The PDF appears to be scanned (no text layer) and OCR is not available on this server."
                )
            raise NoTablesFoundError("No tables were detected in the uploaded PDF.")
        if state.ocr_skipped:
            listed = ",".join(str(p) for p in state.ocr_skipped[:MAX_LISTED_PAGES])
            state.warnings.append(f"Pages without a text layer were skipped because OCR is unavailable: {listed}")
        logger.info("pdf_tables.extracted tables=%d ocr_pages=%d warnings=%d",
                    len(tables), len(state.ocr_pages), len(state.warnings))
        return TableDocument(
            filename=filename, page_count=page_count, page_start=first, page_end=last,
            ocr_pages=tuple(state.ocr_pages), tables=tuple(tables), warnings=tuple(state.warnings),
        )

    # ------------------------------------------------------------------ open / range
    def _open(self, path: Path) -> pymupdf.Document:
        try:
            doc = pymupdf.open(str(path), filetype="pdf")
        except Exception as exc:
            logger.warning("pdf_tables.open_failed error_type=%s", type(exc).__name__)
            raise PDFExtractionError("The uploaded file is not a readable PDF (it may be corrupted).") from exc
        try:
            if doc.needs_pass:      # owner-only restrictions open fine; this is read-only extraction
                raise UnsupportedPDFError("Encrypted or password-protected PDFs are not supported.")
            if not doc.is_pdf or doc.page_count == 0:
                raise PDFExtractionError("The uploaded file is not a readable PDF (it may be corrupted).")
        except Exception:
            doc.close()
            raise
        return doc

    def _resolve_range(self, page_count: int, options: ExtractionOptions) -> tuple[int, int]:
        first = options.page_start
        last = min(options.page_end if options.page_end is not None else page_count, page_count)
        if first > page_count:
            raise InvalidOptionsError(f"page_start is beyond the last page ({page_count}).")
        if last < first:
            raise InvalidOptionsError("page_end must be greater than or equal to page_start.")
        if last - first + 1 > self._s.max_pages:
            raise ResourceLimitError(
                f"At most {self._s.max_pages} pages can be processed per request; use page_start/page_end."
            )
        return first, last

    # ------------------------------------------------------------------ per page
    def _process_page(self, page: pymupdf.Page, page_no: int, options: ExtractionOptions,
                      state: _RunState) -> list[Table]:
        s = self._s
        if max(page.rect.width, page.rect.height) > s.max_page_dimension_pt:
            raise ResourceLimitError("A page exceeds the maximum allowed page dimensions.")
        words = read_words(page)                      # the text-layer probe
        size = (float(page.rect.width), float(page.rect.height))
        needs_ocr = options.ocr is OcrMode.TRUE or (
            options.ocr is OcrMode.AUTO and len(words) < s.ocr_min_words
        )
        if needs_ocr and options.ocr is OcrMode.AUTO and not self._ocr_is_ready():
            state.ocr_skipped.append(page_no)
            return []
        if needs_ocr:
            return self._ocr_page(page, page_no, size, state)
        lattice = self._lattice.detect(page)
        raws = list(lattice)
        if s.borderless:
            raws.extend(
                r for r in self._stream.detect(page)
                if all(bbox_overlap_ratio(r.bbox, l.bbox) < DUPLICATE_OVERLAP for l in lattice)
            )
        return self._build(raws, words, page_no, size, ocr_used=False, state=state)

    def _ocr_page(self, page: pymupdf.Page, page_no: int, size: tuple[float, float],
                  state: _RunState) -> list[Table]:
        s = self._s
        if len(state.ocr_pages) >= s.ocr_max_pages:
            raise ResourceLimitError(
                f"OCR is limited to {s.ocr_max_pages} pages per request; use page_start/page_end."
            )
        if state.ocr_seconds > s.ocr_timeout_seconds:
            raise ExtractionTimeoutError("OCR exceeded the allowed processing time.")
        dpi = effective_dpi(size[0], size[1], s.ocr_dpi, s.ocr_max_pixels)
        started = time.monotonic()
        pdf_bytes = self._ocr.page_to_searchable_pdf(page, dpi=dpi, language=s.ocr_language)
        state.ocr_seconds += time.monotonic() - started
        state.ocr_pages.append(page_no)
        try:
            with pymupdf.open(stream=pdf_bytes, filetype="pdf") as ocr_doc:
                if ocr_doc.page_count < 1:
                    raise OCRProcessingError("OCR processing failed for a page.")
                ocr_page = ocr_doc[0]
                words = read_words(ocr_page)
                raws = self._stream.detect(ocr_page)  # OCR output has no ruling lines
                return self._build(raws, words, page_no, size, ocr_used=True, state=state)
        except OCRProcessingError:
            raise
        except Exception as exc:
            logger.warning("pdf_tables.ocr_read_failed error_type=%s", type(exc).__name__)
            raise OCRProcessingError("OCR processing failed for a page.") from exc

    def _build(self, raws: list[RawTable], words, page_no: int, size: tuple[float, float],
               *, ocr_used: bool, state: _RunState) -> list[Table]:
        built: list[Table] = []
        for raw in sorted(raws, key=lambda r: (round(r.bbox[1]), r.bbox[0])):
            try:
                table = build_table(
                    raw, words, page=page_no, page_size=size, ocr_used=ocr_used,
                    max_rows=self._s.max_rows_per_table, max_columns=self._s.max_columns_per_table,
                )
            except TableTooLargeError:
                state.warnings.append(f"Page {page_no}: a table exceeding the configured size limits was skipped.")
                continue
            if table is not None:
                built.append(table)
        return built

    # ------------------------------------------------------------------ OCR readiness
    def _ocr_is_ready(self) -> bool:
        if self._ocr_ready is None:
            self._ocr_ready = bool(self._s.ocr_enabled and self._ocr.is_available(self._s.ocr_language))
        return self._ocr_ready

    def _require_ocr(self, pages_to_ocr: int) -> None:
        if not self._s.ocr_enabled:
            raise OCRUnavailableError("OCR is disabled on this server.")
        if not self._ocr_is_ready():
            raise OCRUnavailableError("OCR is not available on this server.")
        if pages_to_ocr > self._s.ocr_max_pages:
            raise ResourceLimitError(
                f"OCR is limited to {self._s.ocr_max_pages} pages per request; use page_start/page_end."
            )