"""Library-independent table model shared by the engine and every exporter.

Nothing here imports a PDF, OCR or export library.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

BBox = tuple[float, float, float, float]
_WS_RE = re.compile(r"\s+")


class OutputFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    XLSX = "xlsx"
    HTML = "html"
    MARKDOWN = "markdown"
    IMAGE = "image"


class ImageFormat(str, Enum):
    PNG = "png"
    JPEG = "jpeg"


class OcrMode(str, Enum):
    AUTO = "auto"
    TRUE = "true"
    FALSE = "false"


class DetectionMethod(str, Enum):
    LINES = "lines"   # ruled / bordered tables
    TEXT = "text"     # borderless tables inferred from text alignment


def single_line(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def bbox_overlap_ratio(a: BBox, b: BBox) -> float:
    """Intersection area divided by the smaller box's area."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return (ix * iy) / smaller if smaller > 0 else 0.0


def _round(bbox: BBox) -> list[float]:
    return [round(v, 2) for v in bbox]


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        key = name.casefold()
        seen[key] = seen.get(key, 0) + 1
        out.append(name if seen[key] == 1 else f"{name}_{seen[key]}")
    return out


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True, slots=True)
class RawTable:
    """A detector's output: geometry only, no text."""
    bbox: BBox
    cell_bboxes: tuple[BBox, ...]
    method: DetectionMethod


@dataclass(frozen=True, slots=True)
class Cell:
    row: int
    column: int
    text: str
    page: int
    bbox: BBox | None = None
    rowspan: int = 1
    colspan: int = 1
    is_header: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row, "column": self.column, "text": self.text, "page": self.page,
            "bbox": _round(self.bbox) if self.bbox else None,
            "rowspan": self.rowspan, "colspan": self.colspan, "is_header": self.is_header,
        }


@dataclass(frozen=True, slots=True)
class Table:
    number: int
    pages: tuple[int, ...]                  # >1 entry when merged across pages
    bboxes: tuple[BBox, ...]                # one per page, aligned with ``pages``
    row_count: int
    column_count: int
    header_rows: int                        # 0 = no header detected
    cells: tuple[Cell, ...]
    method: DetectionMethod
    ocr_used: bool
    column_edges: tuple[float, ...] = ()
    page_size: tuple[float, float] = (0.0, 0.0)

    @property
    def table_id(self) -> str:
        return f"table-{self.number:03d}"

    @property
    def page(self) -> int:
        return self.pages[0]

    @property
    def bbox(self) -> BBox:
        return self.bboxes[0]

    def occupancy(self) -> list[list[Cell | None]]:
        """Grid where every position points at the cell covering it."""
        grid: list[list[Cell | None]] = [[None] * self.column_count for _ in range(self.row_count)]
        for cell in self.cells:
            for r in range(cell.row, min(cell.row + cell.rowspan, self.row_count)):
                for c in range(cell.column, min(cell.column + cell.colspan, self.column_count)):
                    grid[r][c] = cell
        return grid

    def matrix(self) -> list[list[str]]:
        """Text grid; positions covered by a merged cell are blank except its origin."""
        grid = [[""] * self.column_count for _ in range(self.row_count)]
        for cell in self.cells:
            grid[cell.row][cell.column] = cell.text
        return grid

    def headers(self) -> list[str]:
        if self.header_rows == 0:
            return [f"Column {i + 1}" for i in range(self.column_count)]
        occupancy = self.occupancy()
        names: list[str] = []
        for c in range(self.column_count):
            parts: list[str] = []
            for r in range(self.header_rows):
                owner = occupancy[r][c]
                text = single_line(owner.text) if owner else ""
                if text and (not parts or parts[-1] != text):
                    parts.append(text)
            names.append(" / ".join(parts) or f"Column {c + 1}")
        return _unique(names)

    def body_rows(self) -> list[list[str]]:
        return self.matrix()[self.header_rows:]

    def records(self) -> list[dict[str, str]]:
        names = self.headers()
        return [dict(zip(names, row)) for row in self.body_rows()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "page": self.page,
            "pages": list(self.pages),
            "bbox": _round(self.bbox),
            "page_bboxes": [{"page": p, "bbox": _round(b)} for p, b in zip(self.pages, self.bboxes)],
            "row_count": self.row_count,
            "column_count": self.column_count,
            "header_rows": self.header_rows,
            "detection_method": self.method.value,
            "ocr_used": self.ocr_used,
            "columns": self.headers(),
            "rows": self.records(),
            "cells": [c.to_dict() for c in self.cells],
        }


@dataclass(frozen=True, slots=True)
class TableDocument:
    filename: str
    page_count: int
    page_start: int
    page_end: int
    ocr_pages: tuple[int, ...]
    tables: tuple[Table, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": {
                "filename": self.filename,
                "page_count": self.page_count,
                "pages_processed": [self.page_start, self.page_end],
                "ocr_pages": list(self.ocr_pages),
                "warnings": list(self.warnings),
            },
            "tables": [t.to_dict() for t in self.tables],
        }