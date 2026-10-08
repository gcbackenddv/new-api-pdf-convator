import logging
from typing import Any
import fitz
from pptx.util import Pt

from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pdf_to_pptx.fonts import clean_xml_string, is_symbol_or_icon_font, normalize_font_name

logger = logging.getLogger(__name__)


def extract_and_add_tables(
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
    default_font: str = "Calibri",
) -> list[fitz.Rect]:
    """Detects tables and creates native PowerPoint tables with preserved row and column geometries.

    Only converts genuinely reliable tables (at least 2 rows and 2 columns).
    Returns the list of table bounding boxes so underlying vector grid lines and cell text
    are not duplicated as standalone shapes or text boxes.
    """
    table_rects: list[fitz.Rect] = []

    try:
        tabs = page.find_tables()
    except Exception as exc:
        logger.debug("Table detection error on page %d: %s", page.number + 1, exc)
        return table_rects

    if not tabs or not getattr(tabs, "tables", None):
        return table_rects

    for t in tabs.tables:
        if t.col_count < 2:
            continue

        # Find rows that have genuine multi-column structure (at least 2 non-empty cells)
        valid_row_indices: list[int] = []
        if hasattr(t, "rows") and t.rows:
            for idx, r in enumerate(t.rows):
                non_none = sum(1 for c in getattr(r, "cells", []) if c is not None)
                if non_none >= 2:
                    valid_row_indices.append(idx)
        else:
            valid_row_indices = list(range(t.row_count))

        # A reliable table must have at least 2 multi-column rows
        if len(valid_row_indices) < 2:
            continue

        start_r = valid_row_indices[0]
        end_r = valid_row_indices[-1]
        active_rows = t.rows[start_r : end_r + 1] if hasattr(t, "rows") and t.rows else []
        active_row_count = len(active_rows) if active_rows else (end_r - start_r + 1)

        # Guard against pathological grids that could exhaust memory
        if active_row_count * t.col_count > 1000:
            continue

        # Trim table bounding box vertically to only the active rows
        if active_rows and hasattr(active_rows[0], "bbox") and hasattr(active_rows[-1], "bbox"):
            y0 = active_rows[0].bbox[1]
            y1 = active_rows[-1].bbox[3]
            bbox = fitz.Rect(t.bbox[0], y0, t.bbox[2], y1)
        else:
            bbox = fitz.Rect(t.bbox)

        if bbox.width <= 10.0 or bbox.height <= 10.0:
            continue

        try:
            left, top, width, height = geom.to_pptx_coords(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            table_shape = slide.shapes.add_table(active_row_count, t.col_count, left, top, width, height)
            ppt_table = table_shape.table

            # Preserve exact column widths from cell coordinates
            if active_rows:
                first_row = active_rows[0]
                if hasattr(first_row, "cells") and first_row.cells:
                    for c_idx, cell_box in enumerate(first_row.cells):
                        if c_idx < t.col_count and cell_box and len(cell_box) == 4:
                            col_pt = max(5.0, cell_box[2] - cell_box[0])
                            ppt_table.columns[c_idx].width = geom.pt_to_emu(col_pt)

                # Set row heights
                for r_idx, r in enumerate(active_rows):
                    if r_idx < active_row_count and hasattr(r, "bbox") and r.bbox:
                        row_pt = max(5.0, r.bbox[3] - r.bbox[1])
                        ppt_table.rows[r_idx].height = geom.pt_to_emu(row_pt)

            # Detect dominant text font on the page to style table cells consistently
            table_font = default_font
            try:
                page_fonts = page.get_fonts()
                if page_fonts:
                    for f_info in page_fonts:
                        f_name = f_info[3] if len(f_info) > 3 else ""
                        norm = normalize_font_name(f_name, default_font="")
                        if norm and not is_symbol_or_icon_font(norm):
                            table_font = norm
                            break
            except Exception:
                pass

            data = t.extract()
            active_data = data[start_r : end_r + 1] if data else []
            for r_idx, row in enumerate(active_data):
                for c_idx, cell_value in enumerate(row):
                    if cell_value is None:
                        continue
                    text_str = clean_xml_string(str(cell_value).strip())
                    if not text_str:
                        continue
                    cell = ppt_table.cell(r_idx, c_idx)
                    cell.margin_left = Pt(2)
                    cell.margin_right = Pt(2)
                    cell.margin_top = Pt(2)
                    cell.margin_bottom = Pt(2)
                    cell.text = text_str
                    for para in cell.text_frame.paragraphs:
                        para.font.name = table_font
                        para.font.size = Pt(10)
                        if r_idx == 0:
                            para.font.bold = True

            table_rects.append(bbox)
            logger.debug(
                "Added native table (%dx%d) on slide %d",
                active_row_count,
                t.col_count,
                page.number + 1,
            )
        except Exception as exc:
            logger.debug("Failed building table on slide %d: %s", page.number + 1, exc)

    return table_rects
