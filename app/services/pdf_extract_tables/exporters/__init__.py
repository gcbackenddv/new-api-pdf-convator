"""Exporter registry. To add a format: new OutputFormat value, new exporter, one line here."""
from __future__ import annotations

from app.services.pdf_extract_tables.exporters.base import ExportSettings, TableExporter
from app.services.pdf_extract_tables.exporters.csv import CSVExporter
from app.services.pdf_extract_tables.exporters.html import HTMLExporter
from app.services.pdf_extract_tables.exporters.image import ImageExporter
from app.services.pdf_extract_tables.exporters.json import JSONExporter
from app.services.pdf_extract_tables.exporters.markdown import MarkdownExporter
from app.services.pdf_extract_tables.exporters.xlsx import XLSXExporter
from app.services.pdf_extract_tables.models import OutputFormat


def get_exporter(fmt: OutputFormat, settings: ExportSettings) -> TableExporter:
    registry: dict[OutputFormat, TableExporter] = {
        OutputFormat.JSON: JSONExporter(),
        OutputFormat.CSV: CSVExporter(settings),
        OutputFormat.XLSX: XLSXExporter(),
        OutputFormat.HTML: HTMLExporter(),
        OutputFormat.MARKDOWN: MarkdownExporter(),
        OutputFormat.IMAGE: ImageExporter(settings),
    }
    return registry[fmt]