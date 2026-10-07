"""Generate JSON / HTML / simple PDF comparison reports."""
from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path
from typing import Optional

import pymupdf as fitz

from .models import CompareResult

logger = logging.getLogger(__name__)


def write_json_report(result: CompareResult, path: Path) -> None:
    path.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )


def write_html_report(result: CompareResult, path: Path) -> None:
    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>PDF Comparison Report</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;}",
        "h1,h2{color:#1a1a2e;}",
        ".summary{display:flex;gap:1rem;flex-wrap:wrap;}",
        ".card{background:#f0f4f8;padding:1rem 1.5rem;border-radius:8px;}",
        ".added{color:#0a7;}.deleted{color:#c00;}.modified{color:#c60;}",
        "table{border-collapse:collapse;width:100%;margin-top:1rem;}",
        "th,td{border:1px solid #ccc;padding:0.5rem;text-align:left;}",
        "th{background:#e8eef5;}",
        "pre{background:#f8f8f8;padding:0.5rem;overflow:auto;max-height:200px;}",
        "</style></head><body>",
        "<h1>PDF Comparison Report</h1>",
        f"<p>Pages compared: {result.pages_compared}</p>",
        "<div class='summary'>",
        f"<div class='card'><b>Added</b><br>{result.summary.added}</div>",
        f"<div class='card'><b>Deleted</b><br>{result.summary.deleted}</div>",
        f"<div class='card'><b>Modified</b><br>{result.summary.modified}</div>",
        f"<div class='card'><b>Moved</b><br>{result.summary.moved}</div>",
        f"<div class='card'><b>Visual</b><br>{result.summary.visual_changes}</div>",
        "</div>",
        "<h2>Differences</h2>",
        "<table><tr><th>Type</th><th>Pages</th><th>Description</th><th>Old</th><th>New</th></tr>",
    ]
    for d in result.differences:
        cls = d.change_type.value
        lines.append(
            f"<tr class='{cls}'>"
            f"<td>{escape(d.change_type.value)}</td>"
            f"<td>{d.page_old or '–'} → {d.page_new or '–'}</td>"
            f"<td>{escape(d.description)}</td>"
            f"<td><pre>{escape(d.old_text or '')}</pre></td>"
            f"<td><pre>{escape(d.new_text or '')}</pre></td>"
            f"</tr>"
        )
    lines.append("</table></body></html>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_pdf_report(result: CompareResult, path: Path) -> None:
    """Simple multi-page PDF summary using PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    y = 50
    page.insert_text((50, y), "PDF Comparison Report", fontsize=18)
    y += 30
    page.insert_text((50, y), f"Pages compared: {result.pages_compared}", fontsize=11)
    y += 20
    s = result.summary
    page.insert_text(
        (50, y),
        f"Added: {s.added}  Deleted: {s.deleted}  Modified: {s.modified}  "
        f"Moved: {s.moved}  Visual: {s.visual_changes}",
        fontsize=10,
    )
    y += 30
    for d in result.differences[:40]:  # limit for readability
        if y > 780:
            page = doc.new_page(width=595, height=842)
            y = 50
        line = f"[{d.change_type.value}] p{d.page_old}→p{d.page_new}: {d.description[:80]}"
        page.insert_text((50, y), line, fontsize=9)
        y += 14
    doc.save(path)
    doc.close()
