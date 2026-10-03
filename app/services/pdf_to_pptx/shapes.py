import logging
from typing import Any
import fitz
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Pt
from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pdf_to_pptx.fonts import parse_color

logger = logging.getLogger(__name__)
MAX_SHAPES_PER_PAGE = 300


def extract_and_add_shapes(
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
    excluded_rects: list[fitz.Rect] | None = None,
) -> int:
    """Extract vector drawings (rectangles, lines, background fills) and add native PPT shapes."""
    excluded = excluded_rects or []
    try:
        drawings = page.get_drawings()
    except Exception as exc:
        logger.warning("Could not read drawings for page %d: %s", page.number + 1, exc)
        return 0

    if not drawings:
        return 0

    added_count = 0
    page_w = page.rect.width
    page_h = page.rect.height

    for draw in drawings:
        if added_count >= MAX_SHAPES_PER_PAGE:
            logger.info("Page %d reached maximum shape limit (%d)", page.number + 1, MAX_SHAPES_PER_PAGE)
            break

        rect = fitz.Rect(draw.get("rect", [0, 0, 0, 0]))
        if rect.width <= 1.0 or rect.height <= 1.0:
            continue

        # Check if drawing falls entirely within an excluded table rectangle
        if any(rect in ex_rect or (abs(rect.x0 - ex_rect.x0) < 2 and abs(rect.y0 - ex_rect.y0) < 2 and abs(rect.x1 - ex_rect.x1) < 2) for ex_rect in excluded):
            continue

        items = draw.get("items", [])
        fill = draw.get("fill")
        stroke_color = draw.get("color")
        line_width = float(draw.get("width", 1.0) or 1.0)

        # Check for full-page background rectangle
        is_full_bg = (rect.width >= page_w * 0.95 and rect.height >= page_h * 0.95)
        # If white full page background without stroke, usually default page background, skip
        if is_full_bg and fill in ([1.0, 1.0, 1.0], (1.0, 1.0, 1.0), 16777215) and not stroke_color:
            continue

        has_rect = any(item[0] == "re" for item in items)
        has_line = any(item[0] == "l" for item in items)

        if not has_rect and not has_line and not fill and not stroke_color:
            continue

        left, top, width, height = geom.to_pptx_coords(rect.x0, rect.y0, rect.x1, rect.y1)

        try:
            shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)

            # Fill handling
            if fill is not None:
                shape.fill.solid()
                shape.fill.fore_color.rgb = parse_color(fill)
            else:
                shape.fill.background()

            # Line / Stroke handling
            if stroke_color is not None:
                shape.line.color.rgb = parse_color(stroke_color)
                shape.line.width = Pt(max(0.25, min(12.0, line_width)))
            else:
                shape.line.fill.background()

            added_count += 1
        except Exception as exc:
            logger.debug("Failed adding shape at %s on page %d: %s", rect, page.number + 1, exc)

    logger.debug("Added %d native shapes to slide %d", added_count, page.number + 1)
    return added_count
