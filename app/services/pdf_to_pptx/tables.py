import logging
from typing import Any
import fitz
from pptx.util import Pt
from app.services.pdf_to_pptx.coordinates import SlideGeometry

logger = logging.getLogger(__name__)


def extract_and_add_tables(
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
    default_font: str = "Calibri",
) -> list[fitz.Rect]:
    """Detects tables and creates native PowerPoint tables. Returns list of table bounding boxes."""
    table_rects: list[fitz.Rect] = []

    try:
        tabs = page.find_tables()
    except Exception as exc:
        logger.debug("Table detection error on page %d: %s", page.number + 1, exc)
        return table_rects

    if not tabs or not getattr(tabs, "tables", None):
        return table_rects

    for t in tabs.tables:
        if t.row_count < 1 or t.col_count < 1:
            continue
        # Guard against pathological grids
        if t.row_count * t.col_count > 1000:
            continue

        bbox = fitz.Rect(t.bbox)
        if bbox.width <= 10.0 or bbox.height <= 10.0:
            continue

        try:
            left, top, width, height = geom.to_pptx_coords(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            table_shape = slide.shapes.add_table(t.row_count, t.col_count, left, top, width, height)
            ppt_table = table_shape.table

            data = t.extract()
            for r_idx, row in enumerate(data):
                for c_idx, cell_value in enumerate(row):
                    if cell_value is None:
                        continue
                    text_str = str(cell_value).strip()
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
                "Added table (%dx%d) on slide %d",
                t.row_count,
                t.col_count,
                page.number + 1,
            )
        except Exception as exc:
            logger.debug("Failed building table on slide %d: %s", page.number + 1, exc)

    return table_rects
