from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.services.pdf_extract_tables.exporters.base import MAX_CELL_CHARS, ExportedFile
from app.services.pdf_extract_tables.models import Table, TableDocument

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_SHEET_TITLE = 31
MIN_COL_WIDTH = 8
MAX_COL_WIDTH = 60
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\\x00-\x1f]")
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")


def sanitize_sheet_title(title: str, used: set[str]) -> str:
    """Excel limits: <=31 chars, none of []:*?/\\, no edge apostrophes, unique (case-insensitive),
    and the name 'History' is reserved."""
    cleaned = _INVALID_SHEET_CHARS.sub("_", title).strip().strip("'")
    cleaned = cleaned[:MAX_SHEET_TITLE].strip().strip("'") or "Sheet"
    if cleaned.casefold() == "history":
        cleaned = "History_"
    candidate, n = cleaned, 2
    while candidate.casefold() in used:
        suffix = f"_{n}"
        candidate = cleaned[: MAX_SHEET_TITLE - len(suffix)] + suffix
        n += 1
    used.add(candidate.casefold())
    return candidate


class XLSXExporter:
    """One sheet per table; merged cells, header styling, frozen header, readable widths.

    Cells are written as strings (never evaluated as formulas), so extracted text such as
    ``=1+1`` stays inert. Numbers are kept as the text found in the PDF.
    """

    def export(self, document: TableDocument, output_dir: Path) -> list[ExportedFile]:
        workbook = Workbook()
        workbook.remove(workbook.active)
        workbook.properties.creator = "PDF Table Extraction API"
        used: set[str] = set()
        for table in document.tables:
            pages = f"p{table.pages[0]}" + (f"-{table.pages[-1]}" if len(table.pages) > 1 else "")
            sheet = workbook.create_sheet(title=sanitize_sheet_title(f"Table {table.number} ({pages})", used))
            self._write_sheet(sheet, table)
        path = output_dir / "extracted-tables.xlsx"
        workbook.save(path)
        return [ExportedFile(path, path.name, XLSX_MEDIA)]

    @staticmethod
    def _write_sheet(sheet: Worksheet, table: Table) -> None:
        widths = [float(MIN_COL_WIDTH)] * table.column_count
        for cell in table.cells:
            row, col = cell.row + 1, cell.column + 1
            text = cell.text[:MAX_CELL_CHARS]
            target = sheet.cell(row=row, column=col, value=text)
            target.data_type = "s"                               # force string: no formula evaluation
            target.border = _BORDER
            target.alignment = Alignment(wrap_text=True, vertical="center" if cell.is_header else "top",
                                         horizontal="center" if cell.is_header else None)
            if cell.is_header:
                target.font = Font(bold=True)
                target.fill = _HEADER_FILL
            if cell.rowspan > 1 or cell.colspan > 1:
                sheet.merge_cells(
                    start_row=row, start_column=col,
                    end_row=min(cell.row + cell.rowspan, table.row_count),
                    end_column=min(cell.column + cell.colspan, table.column_count),
                )
            elif text:
                longest = max(len(line) for line in text.split("\n"))
                widths[cell.column] = max(widths[cell.column], longest + 2)
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(index)].width = min(width, MAX_COL_WIDTH)
        if table.header_rows:
            sheet.freeze_panes = sheet.cell(row=table.header_rows + 1, column=1)