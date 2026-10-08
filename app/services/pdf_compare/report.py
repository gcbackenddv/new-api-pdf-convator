"""Generate professional JSON / HTML / PDF comparison reports."""
from __future__ import annotations

import io
import json
import logging
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional

import pymupdf as fitz
from PIL import Image

from .models import ChangeType, CompareResult

logger = logging.getLogger(__name__)


def write_json_report(result: CompareResult, path: Path) -> None:
    path.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )


def write_html_report(result: CompareResult, path: Path) -> None:
    s = result.summary
    match_rate = 0.0
    if result.page_diffs:
        matched_count = sum(1 for p in result.page_diffs if p.status == "matched")
        match_rate = (matched_count / len(result.page_diffs)) * 100

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PDF Comparison Report</title>
<style>
  :root {{
    --bg-app: #f8fafc;
    --card-bg: #ffffff;
    --border-color: #e2e8f0;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --brand: #2563eb;
    --color-added: #16a34a;
    --bg-added: #dcfce7;
    --color-deleted: #dc2626;
    --bg-deleted: #fee2e2;
    --color-modified: #ea580c;
    --bg-modified: #ffedd5;
    --color-moved: #0284c7;
    --bg-moved: #e0f2fe;
    --color-visual: #9333ea;
    --bg-visual: #f3e8ff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg-app);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 2.5rem 1.5rem;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  header {{
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 2rem;
    margin-bottom: 2rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }}
  .header-title {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1.25rem;
  }}
  h1 {{ font-size: 1.75rem; font-weight: 700; color: var(--text-primary); }}
  .badge-status {{
    padding: 0.35rem 0.85rem;
    border-radius: 9999px;
    font-size: 0.875rem;
    font-weight: 600;
  }}
  .badge-identical {{ background: var(--bg-added); color: var(--color-added); }}
  .badge-differences {{ background: var(--bg-modified); color: var(--color-modified); }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    font-size: 0.9rem;
    color: var(--text-secondary);
  }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }}
  .stat-card {{
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 1.25rem;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    display: flex;
    flex-direction: column;
  }}
  .stat-num {{ font-size: 2rem; font-weight: 700; margin-top: 0.25rem; }}
  .stat-card.added .stat-num {{ color: var(--color-added); }}
  .stat-card.deleted .stat-num {{ color: var(--color-deleted); }}
  .stat-card.modified .stat-num {{ color: var(--color-modified); }}
  .stat-card.moved .stat-num {{ color: var(--color-moved); }}
  .stat-card.visual .stat-num {{ color: var(--color-visual); }}
  .stat-card.total .stat-num {{ color: var(--brand); }}
  .stat-label {{ font-size: 0.825rem; font-weight: 600; text-transform: uppercase; color: var(--text-secondary); }}

  section {{
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.75rem;
    margin-bottom: 2rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }}
  h2 {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 1.25rem; display: flex; align-items: center; gap: 0.5rem; }}

  /* Page Comparison Visuals */
  .page-diff-card {{
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
    background: #ffffff;
  }}
  .page-diff-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    gap: 0.5rem;
  }}
  .page-diff-title {{ font-size: 1.05rem; font-weight: 600; }}
  .page-diff-meta {{ display: flex; gap: 0.75rem; font-size: 0.85rem; color: var(--text-secondary); }}
  .score-badge {{
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    font-weight: 600;
  }}
  .score-high {{ background: var(--bg-added); color: var(--color-added); }}
  .score-mid {{ background: var(--bg-modified); color: var(--color-modified); }}
  .score-low {{ background: var(--bg-deleted); color: var(--color-deleted); }}

  .visual-preview-box {{
    margin-top: 1rem;
    text-align: center;
    background: #f1f5f9;
    padding: 1rem;
    border-radius: 8px;
    border: 1px dashed var(--border-color);
  }}
  .visual-preview-box img {{
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.1);
  }}

  /* Difference Table */
  table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    margin-top: 0.5rem;
  }}
  th, td {{
    padding: 0.85rem 1rem;
    text-align: left;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.9rem;
    vertical-align: top;
  }}
  th {{
    background: #f8fafc;
    font-weight: 600;
    color: var(--text-secondary);
    border-top: 1px solid var(--border-color);
  }}
  tr:hover td {{ background: #fafafa; }}
  .tag {{
    display: inline-block;
    padding: 0.2rem 0.55rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .tag.added {{ background: var(--bg-added); color: var(--color-added); }}
  .tag.deleted {{ background: var(--bg-deleted); color: var(--color-deleted); }}
  .tag.modified {{ background: var(--bg-modified); color: var(--color-modified); }}
  .tag.moved {{ background: var(--bg-moved); color: var(--color-moved); }}
  .tag.visual {{ background: var(--bg-visual); color: var(--color-visual); }}

  .diff-text-box {{
    background: #f8fafc;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    padding: 0.5rem 0.75rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.825rem;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 140px;
    overflow-y: auto;
  }}
  .diff-text-box.old {{ border-left: 3px solid var(--color-deleted); }}
  .diff-text-box.new {{ border-left: 3px solid var(--color-added); }}
  .empty-cell {{ color: #94a3b8; font-style: italic; }}
  footer {{
    text-align: center;
    color: var(--text-secondary);
    font-size: 0.825rem;
    margin-top: 2rem;
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="header-title">
      <h1>PDF Comparison Report</h1>
      <span class="badge-status {'badge-identical' if s.total_differences == 0 else 'badge-differences'}">
        {'No Differences Found (Identical)' if s.total_differences == 0 else f'{s.total_differences} Differences Detected'}
      </span>
    </div>
    <div class="meta-grid">
      <div><strong>Pages Compared:</strong> {result.pages_compared}</div>
      <div><strong>Page Match Rate:</strong> {match_rate:.1f}%</div>
      <div><strong>Total Changes:</strong> {s.total_differences}</div>
      <div><strong>Status:</strong> {'Completed Cleanly' if result.success else 'Errors Encountered'}</div>
    </div>
  </header>

  <div class="stats-grid">
    <div class="stat-card added">
      <span class="stat-label">Added Elements</span>
      <span class="stat-num">{s.added}</span>
    </div>
    <div class="stat-card deleted">
      <span class="stat-label">Deleted Elements</span>
      <span class="stat-num">{s.deleted}</span>
    </div>
    <div class="stat-card modified">
      <span class="stat-label">Modified Text</span>
      <span class="stat-num">{s.modified}</span>
    </div>
    <div class="stat-card moved">
      <span class="stat-label">Moved / Reordered</span>
      <span class="stat-num">{s.moved}</span>
    </div>
    <div class="stat-card visual">
      <span class="stat-label">Visual Regions</span>
      <span class="stat-num">{s.visual_changes}</span>
    </div>
    <div class="stat-card total">
      <span class="stat-label">Total Differences</span>
      <span class="stat-num">{s.total_differences}</span>
    </div>
  </div>
"""

    # Section 1: Page-by-Page Comparison & Visual Overlays
    html += "<section><h2>Page Structure & Visual Analysis</h2>"
    if not result.page_diffs:
        html += "<p style='color:var(--text-secondary);'>No pages to display.</p>"
    else:
        for p in result.page_diffs:
            old_str = f"Page {p.page_old}" if p.page_old else "None"
            new_str = f"Page {p.page_new}" if p.page_new else "None"

            text_score_cls = "score-high" if p.text_similarity >= 0.9 else ("score-mid" if p.text_similarity >= 0.6 else "score-low")
            vis_score_cls = "score-high" if p.visual_similarity >= 0.9 else ("score-mid" if p.visual_similarity >= 0.6 else "score-low")

            html += f"""
            <div class="page-diff-card">
              <div class="page-diff-header">
                <span class="page-diff-title">{old_str} &rarr; {new_str} <span class="tag {p.status}">{p.status}</span></span>
                <div class="page-diff-meta">
                  <span>Text Similarity: <span class="score-badge {text_score_cls}">{p.text_similarity:.1%}</span></span>
                  <span>Visual SSIM: <span class="score-badge {vis_score_cls}">{p.visual_similarity:.1%}</span></span>
                  <span>Changes: <strong>{len(p.differences)}</strong></span>
                </div>
              </div>
            """
            if p.diff_image_data:
                html += f"""
                <div class="visual-preview-box">
                  <div style="font-size:0.85rem; font-weight:600; margin-bottom:0.5rem; color:var(--text-secondary);">
                    Side-by-Side Visual Diff (Red = Removed in Original, Green = Added in Revised)
                  </div>
                  <img src="{p.diff_image_data}" alt="Visual Diff Preview for Page {p.page_old or p.page_new}">
                </div>
                """
            html += "</div>"
    html += "</section>"

    # Section 2: Detailed Difference Log
    html += """
    <section>
      <h2>Detailed Difference Log</h2>
      <table>
        <thead>
          <tr>
            <th style="width: 110px;">Type</th>
            <th style="width: 100px;">Pages</th>
            <th>Description & Coordinates</th>
            <th style="width: 32%;">Original Content</th>
            <th style="width: 32%;">Revised Content</th>
          </tr>
        </thead>
        <tbody>
    """
    if not result.differences:
        html += """
          <tr>
            <td colspan="5" style="text-align:center; padding:2rem; color:var(--text-secondary);">
              No differences detected between the two PDF documents.
            </td>
          </tr>
        """
    else:
        for d in result.differences:
            cls = d.change_type.value
            p_old = f"p.{d.page_old}" if d.page_old else "–"
            p_new = f"p.{d.page_new}" if d.page_new else "–"
            pages_desc = f"{p_old} &rarr; {p_new}" if d.page_old and d.page_new else (p_old if d.page_old else p_new)

            coord_str = ""
            if d.bbox_old:
                coord_str += f"<br><small style='color:var(--text-secondary)'>Old pos: [{', '.join(f'{v:.1f}' for v in d.bbox_old)}]</small>"
            if d.bbox_new:
                coord_str += f"<br><small style='color:var(--text-secondary)'>New pos: [{', '.join(f'{v:.1f}' for v in d.bbox_new)}]</small>"

            old_box = f"<div class='diff-text-box old'>{escape(d.old_text)}</div>" if d.old_text else "<span class='empty-cell'>—</span>"
            new_box = f"<div class='diff-text-box new'>{escape(d.new_text)}</div>" if d.new_text else "<span class='empty-cell'>—</span>"

            html += f"""
              <tr>
                <td><span class="tag {cls}">{escape(d.change_type.value)}</span></td>
                <td><strong>{pages_desc}</strong></td>
                <td>{escape(d.description)}{coord_str}</td>
                <td>{old_box}</td>
                <td>{new_box}</td>
              </tr>
            """
    html += """
        </tbody>
      </table>
    </section>
    <footer>PDF Comparison Service &bull; Automated Visual & Text Audit Report</footer>
  </div>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_pdf_report(
    result: CompareResult,
    path: Path,
    *,
    diff_images: Optional[Dict[int, Any]] = None,
) -> None:
    """Generate a clean, professional PDF comparison report with layout and visual images."""
    doc = fitz.open()
    diff_images = diff_images or {}

    PAGE_W, PAGE_H = 595, 842  # A4
    MARGIN = 40
    USABLE_W = PAGE_W - 2 * MARGIN

    def start_page():
        p = doc.new_page(width=PAGE_W, height=PAGE_H)
        # Header banner
        p.draw_rect(fitz.Rect(0, 0, PAGE_W, 36), color=None, fill=(0.14, 0.22, 0.35))
        p.insert_text((MARGIN, 24), "PDF COMPARISON & AUDIT REPORT", fontsize=11, color=(1, 1, 1))
        # Footer
        p.draw_line(fitz.Point(MARGIN, PAGE_H - 30), fitz.Point(PAGE_W - MARGIN, PAGE_H - 30), color=(0.8, 0.8, 0.8))
        p.insert_text((MARGIN, PAGE_H - 18), "Generated by PDF Comparison API", fontsize=8, color=(0.5, 0.5, 0.5))
        return p

    page = start_page()
    y = 65

    # Document Title
    page.insert_text((MARGIN, y), "PDF Comparison Report", fontsize=18, fontname="helv", color=(0.1, 0.1, 0.2))
    y += 24

    # Executive Overview Box
    s = result.summary
    status_text = "IDENTICAL" if s.total_differences == 0 else f"{s.total_differences} DIFFERENCES FOUND"
    status_bg = (0.86, 0.98, 0.9) if s.total_differences == 0 else (1.0, 0.93, 0.88)
    page.draw_rect(fitz.Rect(MARGIN, y, PAGE_W - MARGIN, y + 40), color=(0.85, 0.85, 0.85), fill=status_bg)
    page.insert_text((MARGIN + 12, y + 25), f"Status: {status_text}", fontsize=12, fontname="helv", color=(0.1, 0.1, 0.1))
    page.insert_text((MARGIN + 260, y + 25), f"Pages Analyzed: {result.pages_compared}", fontsize=10, fontname="helv", color=(0.3, 0.3, 0.3))
    y += 55

    # Stats Summary Cards
    card_w = (USABLE_W - 20) / 3
    card_h = 36
    stats = [
        ("Added Elements", s.added, (0.08, 0.64, 0.29)),
        ("Deleted Elements", s.deleted, (0.86, 0.15, 0.15)),
        ("Modified Text", s.modified, (0.91, 0.35, 0.05)),
        ("Moved Pages", s.moved, (0.01, 0.52, 0.78)),
        ("Visual Regions", s.visual_changes, (0.57, 0.20, 0.91)),
        ("Total Differences", s.total_differences, (0.14, 0.39, 0.92)),
    ]

    for idx, (label, val, col) in enumerate(stats):
        col_idx = idx % 3
        row_idx = idx // 3
        cx = MARGIN + col_idx * (card_w + 10)
        cy = y + row_idx * (card_h + 8)

        page.draw_rect(fitz.Rect(cx, cy, cx + card_w, cy + card_h), color=(0.88, 0.88, 0.88), fill=(0.97, 0.98, 0.99))
        page.insert_text((cx + 8, cy + 16), label, fontsize=8, color=(0.4, 0.4, 0.4))
        page.insert_text((cx + 8, cy + 30), str(val), fontsize=13, fontname="helv", color=col)

    y += 2 * (card_h + 8) + 20

    # Section: Page-by-Page Breakdown
    page.insert_text((MARGIN, y), "Page-by-Page Comparison", fontsize=13, fontname="helv", color=(0.1, 0.1, 0.2))
    y += 18

    for p in result.page_diffs:
        if y > PAGE_H - 100:
            page = start_page()
            y = 55

        old_str = f"Page {p.page_old}" if p.page_old else "–"
        new_str = f"Page {p.page_new}" if p.page_new else "–"
        line_desc = f"{old_str} → {new_str}  [{p.status.upper()}]  |  Text Sim: {p.text_similarity:.1%}  |  SSIM: {p.visual_similarity:.1%}  |  Changes: {len(p.differences)}"
        page.draw_rect(fitz.Rect(MARGIN, y - 10, PAGE_W - MARGIN, y + 10), color=None, fill=(0.95, 0.96, 0.98))
        page.insert_text((MARGIN + 6, y + 4), line_desc, fontsize=9, fontname="helv", color=(0.15, 0.2, 0.25))
        y += 26

        # Embed Visual Diff Image if available for this page
        if p.page_old in diff_images or (p.page_new in diff_images):
            img_obj = diff_images.get(p.page_old) or diff_images.get(p.page_new)
            if img_obj is not None:
                img_w, img_h = img_obj.size
                render_w = min(USABLE_W, 460)
                render_h = render_w * (img_h / img_w)

                if y + render_h > PAGE_H - 50:
                    page = start_page()
                    y = 55

                buf = io.BytesIO()
                img_obj.save(buf, format="JPEG", quality=80)
                page.insert_image(
                    fitz.Rect(MARGIN, y, MARGIN + render_w, y + render_h),
                    stream=buf.getvalue(),
                )
                y += int(render_h) + 20

    # Section: Detailed Differences Log
    if y > PAGE_H - 120:
        page = start_page()
        y = 55

    y += 15
    page.insert_text((MARGIN, y), "Differences Log", fontsize=13, fontname="helv", color=(0.1, 0.1, 0.2))
    y += 18

    for d in result.differences[:50]:
        if y > PAGE_H - 60:
            page = start_page()
            y = 55

        tag = d.change_type.value.upper()
        p_info = f"p{d.page_old or '–'}→p{d.page_new or '–'}"
        desc = d.description[:65]
        page.insert_text((MARGIN, y), f"[{tag}] {p_info}: {desc}", fontsize=8.5, fontname="helv", color=(0.1, 0.1, 0.1))
        y += 14

    doc.save(path)
    doc.close()

