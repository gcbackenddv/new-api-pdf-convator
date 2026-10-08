import io
import logging
from typing import Any
import fitz
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Pt

from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pdf_to_pptx.fonts import parse_color

logger = logging.getLogger(__name__)

MAX_SIMPLE_SHAPES_PER_PAGE = 300
MAX_COMPLEX_VECTOR_FALLBACKS = 30


def _merge_overlapping_rects(rects: list[fitz.Rect], padding: float = 3.0) -> list[fitz.Rect]:
    """Clusters and merges overlapping or adjacent bounding boxes into unified regions."""
    if not rects:
        return []

    current = [fitz.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        new_list: list[fitz.Rect] = []
        skip: set[int] = set()
        for i in range(len(current)):
            if i in skip:
                continue
            r1 = current[i]
            for j in range(i + 1, len(current)):
                if j in skip:
                    continue
                r2 = current[j]
                expanded1 = fitz.Rect(r1.x0 - padding, r1.y0 - padding, r1.x1 + padding, r1.y1 + padding)
                if expanded1.intersects(r2):
                    r1 = r1 | r2
                    skip.add(j)
                    changed = True
            new_list.append(r1)
        current = new_list

    return current


def _is_orthogonal_rectangle(items: list[Any]) -> bool:
    """Checks whether a sequence of line segments forms an orthogonal rectangle."""
    if len(items) not in (4, 5):
        return False
    if not all(it[0] == "l" for it in items):
        return False
    for it in items:
        p1 = it[1]
        p2 = it[2]
        # Must be horizontal or vertical line segment
        if abs(p1[0] - p2[0]) > 0.5 and abs(p1[1] - p2[1]) > 0.5:
            return False
    return True


def extract_and_add_shapes(
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
    excluded_rects: list[fitz.Rect] | None = None,
    dpi: int = 150,
    fallback_rects: list[fitz.Rect] | None = None,
) -> int:
    """Extracts vector drawings cleanly into PowerPoint.

    - Straight lines -> native PowerPoint straight connector lines.
    - Rectangles -> native MSO_SHAPE.RECTANGLE shapes.
    - Ellipses/circles -> native MSO_SHAPE.OVAL shapes.
    - Triangles/polygons -> native MSO_SHAPE.ISOSCELES_TRIANGLE or Freeform shapes.
    - Complex vector illustrations, curves, charts, and icons -> clustered and rendered
      as high-fidelity transparent PNG picture shapes.
    - Never converts vector or drawing paths into corrupted text.
    """
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

    complex_vector_rects: list[fitz.Rect] = []

    for draw in drawings:
        rect = fitz.Rect(draw.get("rect", [0, 0, 0, 0]))

        # Skip shapes inside excluded tables
        if any(rect in ex_rect or (abs(rect.x0 - ex_rect.x0) < 2 and abs(rect.y0 - ex_rect.y0) < 2 and abs(rect.x1 - ex_rect.x1) < 2) for ex_rect in excluded):
            continue

        fill = draw.get("fill")
        stroke_color = draw.get("color")
        line_width = float(draw.get("width", 1.0) or 1.0)
        items = draw.get("items", [])
        if not items:
            continue

        item_types = [it[0] for it in items]

        # -------------------------------------------------------------
        # 1. Background Detection
        # -------------------------------------------------------------
        is_full_bg = (rect.width >= page_w * 0.95 and rect.height >= page_h * 0.95)
        if is_full_bg:
            # If pure white without stroke, skip (default slide is already white)
            if fill in ([1.0, 1.0, 1.0], (1.0, 1.0, 1.0), 16777215) and not stroke_color:
                continue
            # If colored background, apply to slide background
            if fill is not None:
                try:
                    bg_fill = slide.background.fill
                    bg_fill.solid()
                    bg_fill.fore_color.rgb = parse_color(fill)
                    added_count += 1
                    continue
                except Exception:
                    pass  # Fall through to standard shape creation if background assignment fails

        # Skip degenerate zero-size objects that have neither length nor area
        max_dim = max(rect.width, rect.height)
        if max_dim < 1.0:
            continue

        # Check if shape count threshold is exceeded
        if added_count >= MAX_SIMPLE_SHAPES_PER_PAGE:
            complex_vector_rects.append(rect)
            continue

        # -------------------------------------------------------------
        # 2. Straight Line (horizontal, vertical, or diagonal)
        # -------------------------------------------------------------
        if len(items) == 1 and item_types == ["l"]:
            p1 = items[0][1]
            p2 = items[0][2]
            length = ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5
            if length < 1.0:
                continue

            bx, by, _, _ = geom.to_pptx_coords(p1[0], p1[1], p1[0] + 1, p1[1] + 1)
            ex, ey, _, _ = geom.to_pptx_coords(p2[0], p2[1], p2[0] + 1, p2[1] + 1)

            try:
                connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, bx, by, ex, ey)
                line_color = stroke_color if stroke_color is not None else fill
                if line_color is not None:
                    connector.line.color.rgb = parse_color(line_color)
                    connector.line.width = Pt(max(0.25, min(12.0, line_width)))
                added_count += 1
                continue
            except Exception as exc:
                logger.debug("Failed adding connector line: %s", exc)

        # -------------------------------------------------------------
        # 3. Rectangle (explicit "re" or closed orthogonal lines)
        # -------------------------------------------------------------
        if rect.width >= 1.0 and rect.height >= 1.0:
            is_rect = ("re" in item_types) or _is_orthogonal_rectangle(items)
            if is_rect:
                left, top, width, height = geom.to_pptx_coords(rect.x0, rect.y0, rect.x1, rect.y1)
                try:
                    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
                    if fill is not None:
                        shape.fill.solid()
                        shape.fill.fore_color.rgb = parse_color(fill)
                    else:
                        shape.fill.background()

                    if stroke_color is not None:
                        shape.line.color.rgb = parse_color(stroke_color)
                        shape.line.width = Pt(max(0.25, min(12.0, line_width)))
                    else:
                        shape.line.fill.background()

                    added_count += 1
                    continue
                except Exception as exc:
                    logger.debug("Failed adding rectangle shape: %s", exc)

        # -------------------------------------------------------------
        # 4. Ellipse / Circle / Oval (curves forming closed circular/oval shape)
        # -------------------------------------------------------------
        has_curves = "c" in item_types or "qu" in item_types
        if has_curves and rect.width >= 2.0 and rect.height >= 2.0:
            aspect = rect.width / max(1.0, rect.height)
            if 0.70 <= aspect <= 1.40 and len(items) <= 16:
                left, top, width, height = geom.to_pptx_coords(rect.x0, rect.y0, rect.x1, rect.y1)
                try:
                    oval = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, width, height)
                    if fill is not None:
                        oval.fill.solid()
                        oval.fill.fore_color.rgb = parse_color(fill)
                    else:
                        oval.fill.background()

                    if stroke_color is not None:
                        oval.line.color.rgb = parse_color(stroke_color)
                        oval.line.width = Pt(max(0.25, min(12.0, line_width)))
                    else:
                        oval.line.fill.background()

                    added_count += 1
                    continue
                except Exception as exc:
                    logger.debug("Failed adding oval shape: %s", exc)

        # -------------------------------------------------------------
        # 5. Triangles and Simple Polygons (3-8 straight lines)
        # -------------------------------------------------------------
        if not has_curves and all(t == "l" for t in item_types) and 3 <= len(items) <= 8 and rect.width >= 2.0 and rect.height >= 2.0:
            left, top, width, height = geom.to_pptx_coords(rect.x0, rect.y0, rect.x1, rect.y1)
            if len(items) == 3:
                try:
                    triangle = slide.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE, left, top, width, height)
                    if fill is not None:
                        triangle.fill.solid()
                        triangle.fill.fore_color.rgb = parse_color(fill)
                    else:
                        triangle.fill.background()

                    if stroke_color is not None:
                        triangle.line.color.rgb = parse_color(stroke_color)
                        triangle.line.width = Pt(max(0.25, min(12.0, line_width)))
                    else:
                        triangle.line.fill.background()

                    added_count += 1
                    continue
                except Exception as exc:
                    logger.debug("Failed adding triangle shape: %s", exc)

            # Polygons via Freeform builder
            try:
                pts = [it[1] for it in items] + [items[-1][2]]
                p0_x, p0_y, _, _ = geom.to_pptx_coords(pts[0][0], pts[0][1], pts[0][0] + 1, pts[0][1] + 1)
                builder = slide.shapes.build_freeform(p0_x, p0_y)
                pt_coords = []
                for pt in pts[1:]:
                    px, py, _, _ = geom.to_pptx_coords(pt[0], pt[1], pt[0] + 1, pt[1] + 1)
                    pt_coords.append((px, py))
                builder.add_line_segments(pt_coords)
                poly_shape = builder.convert_to_shape()

                if fill is not None:
                    poly_shape.fill.solid()
                    poly_shape.fill.fore_color.rgb = parse_color(fill)
                else:
                    poly_shape.fill.background()

                if stroke_color is not None:
                    poly_shape.line.color.rgb = parse_color(stroke_color)
                    poly_shape.line.width = Pt(max(0.25, min(12.0, line_width)))
                else:
                    poly_shape.line.fill.background()

                added_count += 1
                continue
            except Exception as exc:
                logger.debug("Failed building freeform polygon: %s", exc)

        # -------------------------------------------------------------
        # 6. Complex Vectors (intricate curves, charts, CAD lines, logos)
        # -------------------------------------------------------------
        complex_vector_rects.append(rect)

    # Render clustered complex vectors as crisp transparent PNG picture shapes
    if complex_vector_rects:
        merged_regions = _merge_overlapping_rects(complex_vector_rects)[:MAX_COMPLEX_VECTOR_FALLBACKS]
        for region in merged_regions:
            if region.width <= 2.0 or region.height <= 2.0:
                continue
            try:
                pix = page.get_pixmap(clip=region, dpi=dpi, alpha=True)
                img_bytes = pix.tobytes("png")
                del pix

                buf = io.BytesIO(img_bytes)
                left, top, width, height = geom.to_pptx_coords(region.x0, region.y0, region.x1, region.y1)
                slide.shapes.add_picture(buf, left, top, width, height)
                buf.close()
                added_count += 1
                if fallback_rects is not None:
                    fallback_rects.append(region)
            except Exception as exc:
                logger.debug("Failed rendering complex vector fallback image: %s", exc)

    logger.debug("Added %d vector shapes/illustrations to slide %d", added_count, page.number + 1)
    return added_count
