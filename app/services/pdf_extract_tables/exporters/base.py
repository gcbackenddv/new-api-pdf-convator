"""Exporter contract and shared helpers. Exporters depend only on the model, never on PyMuPDF."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.services.pdf_extract_tables.models import ImageFormat, Table, TableDocument

MAX_CELL_CHARS = 32767          # Excel's per-cell limit; also a sane bound for every format

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_NUMBER_RE = re.compile(r"^[+-]?(\d[\d,]*\.?\d*|\.\d+)([eE][+-]?\d+)?%?$")


@dataclass(frozen=True, slots=True)
class ExportedFile:
    path: Path
    filename: str
    media_type: str
    inline: bool = False


@dataclass(frozen=True, slots=True)
class ExportSettings:
    csv_bom: bool = True
    image_format: ImageFormat = ImageFormat.PNG
    image_max_rows: int = 200
    image_max_pixels: int = 20_000_000
    latin_font_path: str = ""
    bengali_font_path: str = ""


class TableExporter(Protocol):
    def export(self, document: TableDocument, output_dir: Path) -> list[ExportedFile]:
        """Write one or more files into ``output_dir`` and describe them."""
        ...


def describe_pages(table: Table) -> str:
    if len(table.pages) == 1:
        return f"page {table.pages[0]}"
    return f"pages {table.pages[0]}-{table.pages[-1]}"


def neutralize_formula(text: str) -> str:
    """CSV/spreadsheet injection guard: prefix risky text so it is never evaluated.

    Real numbers such as ``-5`` or ``+3.2`` are left untouched.
    """
    if len(text) > 1 and text[0] in _FORMULA_PREFIXES and not _NUMBER_RE.match(text.strip()):
        return "'" + text
    return text