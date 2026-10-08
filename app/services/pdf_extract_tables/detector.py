"""Table detectors. The only module (with ocr.py and the engine) that touches PyMuPDF.

Detectors return geometry only (``RawTable``); text is assigned later by the normalizer.
"""
from __future__ import annotations

import logging
from typing import Protocol

import pymupdf

from app.services.pdf_extract_tables.models import (
    DetectionMethod, RawTable, Word, bbox_overlap_ratio,
)

logger = logging.getLogger(__name__)


class TableDetector(Protocol):
    method: DetectionMethod

    def detect(self, page: pymupdf.Page, clip: pymupdf.Rect | None = None) -> list[RawTable]: ...


class _PyMuPDFDetector:
    method: DetectionMethod
    _strategy: str

    def detect(self, page: pymupdf.Page, clip: pymupdf.Rect | None = None) -> list[RawTable]:
        kwargs: dict[str, object] = {"strategy": self._strategy}
        if clip is not None:
            kwargs["clip"] = clip
        try:
            found = list(page.find_tables(**kwargs).tables)
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


class StreamDetector:
    """Borderless tables inferred from text alignment."""
    method = DetectionMethod.TEXT

    def detect(self, page: pymupdf.Page, clip: pymupdf.Rect | None = None) -> list[RawTable]:
        # Multi-pass detection to capture various borderless table formats:
        # Pass 1: Standard text alignment with min_words_vertical=2 (captures standard 2+ row tables)
        # Pass 2: Refined/adjusted text alignment with snap tolerance for slightly misaligned columns
        # Pass 3: Relaxed pass for compact / 2-row tables that default PyMuPDF skips
        passes = (
            {"strategy": "text", "min_words_vertical": 2},
            {"strategy": "text", "min_words_vertical": 2, "snap_x_tolerance": 5, "text_x_tolerance": 5},
        )
        seen_bboxes: list[tuple[float, float, float, float]] = []
        raws: list[RawTable] = []

        for p_kwargs in passes:
            kwargs: dict[str, object] = dict(p_kwargs)
            if clip is not None:
                kwargs["clip"] = clip
            try:
                found = list(page.find_tables(**kwargs).tables)
            except Exception as exc:
                logger.warning("pdf_tables.detect_failed method=%s error_type=%s",
                               self.method.value, type(exc).__name__)
                continue

            for table in found:
                try:
                    cells = tuple(tuple(float(v) for v in c) for c in table.cells)
                    bbox = tuple(float(v) for v in table.bbox)
                except Exception:
                    continue
                if not cells:
                    continue
                # Avoid duplicates across passes
                if any(bbox_overlap_ratio(bbox, sb) > 0.6 for sb in seen_bboxes):
                    continue

                seen_bboxes.append(bbox)
                raws.append(RawTable(bbox=bbox, cell_bboxes=cells, method=self.method))

            if raws:
                break

        return raws


def read_words(page: pymupdf.Page) -> list[Word]:
    try:
        raw = page.get_text("words")
    except Exception as exc:
        logger.warning("pdf_tables.words_failed error_type=%s", type(exc).__name__)
        return []
    return [Word(w[4], float(w[0]), float(w[1]), float(w[2]), float(w[3])) for w in raw if w[4].strip()]