import logging
from typing import Any
import fitz
from pptx.util import Pt

from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pdf_to_pptx.fonts import clean_xml_string

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
        # A reliable table must have at least 2 rows and 2 columns
        if t.row_count < 2 or t.col_count < 2:
            continue
        # Guard against pathological grids that could exhaust memory
        if t.row_count * t.col_count > 1000:
            continue

        bbox = fitz.Rect(t.bbox)
        if bbox.width <= 10.0 or bbox.height <= 10.0:
            continue

        try:
            left, top, width, height = geom.to_pptx_coords(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            table_shape = slide.shapes.add_table(t.row_count, t.col_count, left, top, width, height)
            ppt_table = table_shape.table

            # Preserve exact column widths from cell coordinates
            if hasattr(t, "rows") and t.rows:
                first_row = t.rows[0]
                if hasattr(first_row, "cells") and first_row.cells:
                    for c_idx, cell_box in enumerate(first_row.cells):
                        if c_idx < t.col_count and cell_box and len(cell_box) == 4:
                            col_pt = max(5.0, cell_box[2] - cell_box[0])
                            ppt_table.columns[c_idx].width = geom.pt_to_emu(col_pt)

                # Set row heights
                for r_idx, r in enumerate(t.rows):
                    if r_idx < t.row_count and hasattr(r, "bbox") and r.bbox:
                        row_pt = max(5.0, r.bbox[3] - r.bbox[1])
                        ppt_table.rows[r_idx].height = geom.pt_to_emu(row_pt)

            data = t.extract()
            for r_idx, row in enumerate(data):
                for c_idx, cell_value in enumerate(row):
                    if cell_value is None:
                        continue
                    text_str = clean_xml_string(str(cell_value).strip())
                    if not text_str:
                        continue
                    cell = ppt_table.cell(r_idx, c_idx)
                    cell.text = text_str
                    for para in cell.text_frame.paragraphs:
                        para.font.name = default_font
                        para.font.size = Pt(10)
                        if r_idx == 0:
                            para.font.bold = True

            table_rects.append(bbox)
            logger.debug(
                "Added native table (%dx%d) on slide %d",
                t.row_count,
                t.col_count,
                page.number + 1,
            )
        except Exception as exc:
            logger.debug("Failed building table on slide %d: %s", page.number + 1, exc)

    return table_rects
