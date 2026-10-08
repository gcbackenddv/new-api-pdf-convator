from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from app.services.pdf_extract_tables.exporters.base import ExportedFile, describe_pages
from app.services.pdf_extract_tables.models import Cell, Table, TableDocument

_STYLE = (
    "body{font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;margin:2rem auto;max-width:1200px;color:#1e293b;background:#f8fafc;padding:0 1rem}"
    "h1{font-size:1.5rem;color:#0f172a;margin-bottom:1.5rem;border-bottom:2px solid #e2e8f0;padding-bottom:0.5rem}"
    "section{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:1.5rem;margin-bottom:2rem;box-shadow:0 1px 3px rgba(0,0,0,0.05);overflow-x:auto}"
    "h2{font-size:1.15rem;color:#1e293b;margin:0 0 1rem;padding-bottom:0.5rem;border-bottom:1px solid #e2e8f0;font-weight:600}"
    "table{border-collapse:collapse;width:100%;margin:0}"
    "th,td{border:1px solid #cbd5e1;padding:8px 12px;vertical-align:middle;text-align:center;font-size:0.9rem}"
    "th{background:#d9e1f2;font-weight:600;color:#0f172a}"
    "tr:nth-child(even) td{background:#f8fafc}"
)


def _text(value: str) -> str:
    """Escape everything; only our own <br> is emitted as markup."""
    return html.escape(value, quote=True).replace("\n", "<br>")


class HTMLExporter:
    def export(self, document: TableDocument, output_dir: Path) -> list[ExportedFile]:
        parts = [
            '<!doctype html><html lang="en"><head><meta charset="utf-8">',
            f"<title>{html.escape(document.filename)}: extracted tables</title>",
            f"<style>{_STYLE}</style></head><body>",
            f"<h1>{html.escape(document.filename)}</h1>",
        ]
        for table in document.tables:
            title_text = table.title or f"Table {table.number} ({describe_pages(table)})"
            parts.append(f"<section><h2>{html.escape(title_text)}</h2>")
            parts.append(self._table(table))
            parts.append("</section>")
        parts.append("</body></html>")
        path = output_dir / "extracted-tables.html"
        path.write_text("".join(parts), encoding="utf-8")
        return [ExportedFile(path, path.name, "text/html")]

    @staticmethod
    def _table(table: Table) -> str:
        by_row: dict[int, list[Cell]] = defaultdict(list)
        for cell in table.cells:
            by_row[cell.row].append(cell)

        def render_row(row: int) -> str:
            limit = table.header_rows if row < table.header_rows else table.row_count
            out = ["<tr>"]
            for cell in sorted(by_row[row], key=lambda c: c.column):
                tag = "th" if cell.is_header else "td"
                attrs = ' scope="col"' if cell.is_header else ""
                rowspan = min(cell.rowspan, limit - cell.row)         # never cross thead/tbody
                colspan = min(cell.colspan, table.column_count - cell.column)
                if rowspan > 1:
                    attrs += f' rowspan="{rowspan}"'
                if colspan > 1:
                    attrs += f' colspan="{colspan}"'
                out.append(f"<{tag}{attrs}>{_text(cell.text)}</{tag}>")
            out.append("</tr>")
            return "".join(out)

        head = "".join(render_row(r) for r in range(table.header_rows))
        body = "".join(render_row(r) for r in range(table.header_rows, table.row_count))
        return f"<table>{'<thead>' + head + '</thead>' if head else ''}<tbody>{body}</tbody></table>"