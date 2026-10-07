"""Main PDF comparison orchestrator."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pymupdf as fitz

from app.config import get_settings
from app.services.pdf_processing.validator import validate_pdf
from app.services.pdf_processing.renderer import render_page_to_image

from .models import ChangeType, CompareResult, Difference, PageDiff
from .text_compare import text_diff, extract_page_text, similarity_ratio
from .visual_compare import visual_similarity, find_visual_changes
from .page_compare import match_pages
from .diff import build_summary
from .report import write_json_report, write_html_report, write_pdf_report

logger = logging.getLogger(__name__)


def compare_pdfs(
    path_old: Path,
    path_new: Path,
    *,
    output_dir: Path,
    do_visual: bool = True,
    do_text: bool = True,
) -> CompareResult:
    """
    Full comparison pipeline:
    1. Validate both PDFs
    2. Match pages (handles reordering)
    3. Text diff per matched pair
    4. Visual diff per matched pair
    5. Record added/deleted pages
    6. Generate reports
    """
    validate_pdf(path_old)
    validate_pdf(path_new)

    doc_old = fitz.open(path_old)
    doc_new = fitz.open(path_new)

    try:
        matches = match_pages(doc_old, doc_new)
        all_diffs: list[Difference] = []
        page_diffs: list[PageDiff] = []

        for old_idx, new_idx, score in matches:
            if old_idx is not None and new_idx is not None:
                # Matched pair
                text_sim = score
                vis_sim = 1.0
                pair_diffs: list[Difference] = []

                if do_text:
                    t_old = extract_page_text(doc_old[old_idx])
                    t_new = extract_page_text(doc_new[new_idx])
                    pair_diffs.extend(
                        text_diff(t_old, t_new, page_old=old_idx + 1, page_new=new_idx + 1)
                    )
                    text_sim = similarity_ratio(t_old, t_new)

                if do_visual:
                    try:
                        img_old = render_page_to_image(doc_old, old_idx, dpi=100)
                        img_new = render_page_to_image(doc_new, new_idx, dpi=100)
                        vis_sim = visual_similarity(img_old, img_new)
                        if vis_sim < 0.92:
                            pair_diffs.extend(
                                find_visual_changes(
                                    img_old, img_new,
                                    page_old=old_idx + 1, page_new=new_idx + 1,
                                )
                            )
                    except Exception as exc:
                        logger.warning("Visual compare failed p%d/p%d: %s", old_idx + 1, new_idx + 1, exc)

                # Detect move (different page numbers)
                status = "matched"
                if old_idx != new_idx and text_sim > 0.85:
                    status = "moved"
                    all_diffs.append(
                        Difference(
                            change_type=ChangeType.MOVED,
                            page_old=old_idx + 1,
                            page_new=new_idx + 1,
                            description=f"Page moved from {old_idx + 1} to {new_idx + 1}",
                            severity="low",
                        )
                    )
                elif pair_diffs:
                    status = "modified"

                all_diffs.extend(pair_diffs)
                page_diffs.append(
                    PageDiff(
                        page_old=old_idx + 1,
                        page_new=new_idx + 1,
                        status=status,
                        text_similarity=round(text_sim, 3),
                        visual_similarity=round(vis_sim, 3),
                        differences=pair_diffs,
                    )
                )

            elif old_idx is not None:
                # Deleted page
                all_diffs.append(
                    Difference(
                        change_type=ChangeType.DELETED,
                        page_old=old_idx + 1,
                        description=f"Page {old_idx + 1} deleted",
                        severity="high",
                    )
                )
                page_diffs.append(
                    PageDiff(page_old=old_idx + 1, status="deleted")
                )
            else:
                # Added page
                all_diffs.append(
                    Difference(
                        change_type=ChangeType.ADDED,
                        page_new=new_idx + 1,
                        description=f"Page {new_idx + 1} added",
                        severity="high",
                    )
                )
                page_diffs.append(
                    PageDiff(page_new=new_idx + 1, status="added")
                )

        summary = build_summary(all_diffs, page_diffs)
        result = CompareResult(
            success=True,
            pages_compared=max(doc_old.page_count, doc_new.page_count),
            summary=summary,
            differences=all_diffs,
            page_diffs=page_diffs,
        )

        # Reports
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "compare-report.json"
        html_path = output_dir / "compare-report.html"
        pdf_path = output_dir / "compare-report.pdf"
        write_json_report(result, json_path)
        write_html_report(result, html_path)
        write_pdf_report(result, pdf_path)
        result.reports = {
            "json": str(json_path.name),
            "html": str(html_path.name),
            "pdf": str(pdf_path.name),
        }
        return result

    finally:
        doc_old.close()
        doc_new.close()
