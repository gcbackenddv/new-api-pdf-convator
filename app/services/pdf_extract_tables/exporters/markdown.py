from __future__ import annotations

import re
from pathlib import Path

from app.services.pdf_extract_tables.exporters.base import ExportedFile, describe_pages
from app.services.pdf_extract_tables.models import Table, TableDocument

_SPECIAL = re.compile(r"([\\`*_\[\]<>|~])")


def _cell(text: str) -> str:
    """Escape Markdown/HTML-significant characters; newlines become <br>."""
    return _SPECIAL.sub(r"\\\1", text).replace("\r\n", "\n").replace("\n", "<br>")


def _row(values: list[str]) -> str:
    return "| " + " | ".join(_cell(v) for v in values) + " |"


class MarkdownExporter:
    """GitHub-flavoured tables. Markdown cannot express merged cells: a merged cell's text sits in
    its first position and the covered positions are blank. A header row is always emitted
    (``Column N`` when none was detected)."""

    def export(self, document: TableDocument, output_dir: Path) -> list[ExportedFile]:
        blocks = [f"{self._render(table)}" for table in document.tables]
        path = output_dir / "extracted-tables.md"
        path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        return [ExportedFile(path, path.name, "text/markdown")]

    @staticmethod
    def _render(table: Table) -> str:
        header = table.headers()
        title_text = table.title or f"Table {table.number} ({describe_pages(table)})"
        lines = [
            f"## {title_text}", "",
            _row(header),
            "| " + " | ".join(":---:" for _ in header) + " |",
            *(_row(r) for r in table.body_rows()),
        ]
        return "\n".join(lines)