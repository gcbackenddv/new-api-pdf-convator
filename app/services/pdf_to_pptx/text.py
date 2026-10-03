import math
import logging
from typing import Any
import fitz
from pptx.util import Pt, Emu
from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pdf_to_pptx.fonts import (
    is_bold,
    is_italic,
    normalize_font_name,
    parse_color,
)

logger = logging.getLogger(__name__)


def extract_and_add_text(
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
    excluded_rects: list[fitz.Rect] | None = None,
    default_font: str = "Calibri",
) -> int:
    """Extract digital text and place it as native, editable PowerPoint text boxes."""
    excluded = excluded_rects or []
    try:
        page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_SEARCH)
    except Exception as exc:
        logger.warning("Could not read text dict on page %d: %s", page.number + 1, exc)
        return 0

    blocks = page_dict.get("blocks", [])
    if not blocks:
        return 0

    added_count = 0

    for block in blocks:
        if block.get("type") != 0:  # 0 is text block
            continue

        bbox_raw = block.get("bbox")
        if not bbox_raw or len(bbox_raw) != 4:
            continue

        b_rect = fitz.Rect(bbox_raw)
        if b_rect.width <= 1.0 or b_rect.height <= 1.0:
            continue

        # Skip text blocks inside tables
        if any(b_rect in ex_rect or ex_rect.contains(b_rect) for ex_rect in excluded):
            continue

        lines = block.get("lines", [])
        if not lines:
            continue

        # Verify that there is at least one non-empty span
        has_content = False
        for line in lines:
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    has_content = True
                    break
            if has_content:
                break
        if not has_content:
            continue

        left, top, width, height = geom.to_pptx_coords(b_rect.x0, b_rect.y0, b_rect.x1, b_rect.y1)
        # Give slight horizontal padding (6%) to account for font metric variances in Office
        width = Emu(int(width * 1.06))

        try:
            tx_box = slide.shapes.add_textbox(left, top, width, height)
            tf = tx_box.text_frame
            tf.word_wrap = True
            tf.margin_left = Pt(1)
            tf.margin_right = Pt(1)
            tf.margin_top = Pt(1)
            tf.margin_bottom = Pt(1)

            # Check rotation from the first line direction vector
            first_dir = lines[0].get("dir", (1.0, 0.0))
            if len(first_dir) == 2 and (abs(first_dir[1]) > 0.05 or first_dir[0] < 0.95):
                angle_deg = math.degrees(math.atan2(first_dir[1], first_dir[0]))
                if abs(angle_deg) > 1.0:
                    tx_box.rotation = angle_deg

            para_index = 0
            for line_idx, line in enumerate(lines):
                spans = line.get("spans", [])
                if not spans:
                    continue

                if para_index == 0:
                    p = tf.paragraphs[0]
                else:
                    p = tf.add_paragraph()
                para_index += 1

                for span in spans:
                    text_content = span.get("text", "")
                    if not text_content:
                        continue

                    run = p.add_run()
                    run.text = text_content
                    font_raw = span.get("font", "")
                    run.font.name = normalize_font_name(font_raw, default_font)

                    size_val = float(span.get("size", 12.0) or 12.0)
                    size_val = max(4.0, min(144.0, size_val))
                    run.font.size = Pt(size_val)

                    flags = int(span.get("flags", 0) or 0)
                    run.font.bold = is_bold(flags, font_raw)
                    run.font.italic = is_italic(flags, font_raw)
                    run.font.color.rgb = parse_color(span.get("color", 0))

            added_count += 1
        except Exception as exc:
            logger.debug("Failed adding text box on slide %d: %s", page.number + 1, exc)

    logger.debug("Added %d editable text boxes to slide %d", added_count, page.number + 1)
    return added_count
