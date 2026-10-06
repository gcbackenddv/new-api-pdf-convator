"""Table detectors. The only module (with ocr.py and the engine) that touches PyMuPDF.

Detectors return geometry only (``RawTable``); text is assigned later by the normalizer.
"""
from __future__ import annotations

import logging
from typing import Protocol

import pymupdf

from app.services.pdf_extract_tables.models import DetectionMethod, RawTable, Word

logger = logging.getLogger(__name__)


class TableDetector(Protocol):
    method: DetectionMethod

    def detect(self, page: pymupdf.Page) -> list[RawTable]: ...


class _PyMuPDFDetector:
    method: DetectionMethod
    _strategy: str

    def detect(self, page: pymupdf.Page) -> list[RawTable]:
        try:
            found = list(page.find_tables(strategy=self._strategy).tables)
        except Exception as exc:  # keep going: one bad page must not fail the document
            logger.warning("pdf_tables.detect_failed method=%s error_type=%s",
                           self.method.value, type(exc).__name__)
            return []
        raws: list[RawTable] = []
        for table in found:
            try:
                cells = tuple(tuple(float(v) for v in c) for c in table.cells)
                bbox = tuple(float(v) for v in table.bbox)
            except Exception:
                continue
            if cells:
                raws.append(RawTable(bbox=bbox, cell_bboxes=cells, method=self.method))  # type: ignore[arg-type]
        return raws


class LatticeDetector(_PyMuPDFDetector):
    """Tables with visible ruling lines or cell borders."""
    method = DetectionMethod.LINES
    _strategy = "lines"


class StreamDetector(_PyMuPDFDetector):
    """Borderless tables inferred from text alignment."""
    method = DetectionMethod.TEXT
    _strategy = "text"


def read_words(page: pymupdf.Page) -> list[Word]:
    try:
        raw = page.get_text("words")
    except Exception as exc:
        logger.warning("pdf_tables.words_failed error_type=%s", type(exc).__name__)
        return []
    return [Word(w[4], float(w[0]), float(w[1]), float(w[2]), float(w[3])) for w in raw if w[4].strip()]