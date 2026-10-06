from __future__ import annotations

import csv
from pathlib import Path

from app.services.pdf_extract_tables.exporters.base import (
    MAX_CELL_CHARS, ExportedFile, ExportSettings, neutralize_formula,
)
from app.services.pdf_extract_tables.models import Table, TableDocument


class CSVExporter:
    """One CSV per table. UTF-8 (with BOM by default so Excel reads Bengali correctly).

    Multi-row headers are flattened into one header row. A table with no detected
    header is written without a synthetic header row.
    """

    def __init__(self, settings: ExportSettings) -> None:
        self._encoding = "utf-8-sig" if settings.csv_bom else "utf-8"

    def export(self, document: TableDocument, output_dir: Path) -> list[ExportedFile]:
        files: list[ExportedFile] = []
        for table in document.tables:
            path = output_dir / f"{table.table_id}.csv"
            with open(path, "w", encoding=self._encoding, newline="") as fh:
                writer = csv.writer(fh)                       # RFC 4180 quoting, CRLF line ends
                for row in self._rows(table):
                    writer.writerow(neutralize_formula(cell[:MAX_CELL_CHARS]) for cell in row)
            files.append(ExportedFile(path, path.name, "text/csv"))
        return files

    @staticmethod
    def _rows(table: Table) -> list[list[str]]:
        if table.header_rows == 0:
            return table.matrix()
        return [table.headers(), *table.body_rows()]