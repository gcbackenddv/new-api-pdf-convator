import logging
from typing import Any
import fitz
from pptx.util import Pt

from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pdf_to_pptx.fonts import clean_xml_string, is_garbage_or_symbol_glyph, normalize_font_name

logger = logging.getLogger(__name__)


def is_scanned_page(page: fitz.Page) -> bool:
    """Determine if a page is a scanned document.

    A page is considered scanned ONLY if:
    1. It contains NO extractable digital text.
    2. It contains NO native vector drawings or CAD paths.
    3. It is dominated by a raster image (covering >= 50% of the page).

    Pages containing vector illustrations, charts, or digital elements are
    NEVER classified as scanned documents.
    """
    try:
        text = page.get_text().strip()
        if len(text) > 0:
            return False

        # If page contains vector drawings, it is a digital vector page, not a scan
        drawings = page.get_drawings()
        if len(drawings) > 0:
            return False

        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return False

        image_infos = page.get_image_info()
        for info in image_infos:
            bbox = info.get("bbox")
            if bbox and len(bbox) == 4:
                w = abs(bbox[2] - bbox[0])
                h = abs(bbox[3] - bbox[1])
                if (w * h) >= 0.50 * page_area:
                    return True

        return len(page.get_images()) > 0
    except Exception as exc:
        logger.debug("Error checking scanned page %d: %s", page.number + 1, exc)
        return False


def perform_ocr_on_page(
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
    default_font: str = "Calibri",
    languages: str = "eng,ben",
    dpi: int = 300,
) -> bool:
    """Attempts OCR on a genuine scanned page and adds editable text boxes.

    Returns True if editable text was added, False otherwise.
    """
    # Sanitize language codes
    valid_langs: list[str] = []
    for l_item in languages.replace("+", ",").split(","):
        code = l_item.strip().lower()
        if code in ("eng", "en"):
            valid_langs.append("eng")
        elif code in ("ben", "bn"):
            valid_langs.append("ben")
        elif code and code not in ("auto",):
            valid_langs.append(code)

    if not valid_langs:
        valid_langs = ["eng"]

    lang_str = "+".join(dict.fromkeys(valid_langs))

    # 1. Attempt PyMuPDF Tesseract OCR integration
    try:
        try:
            tp = page.get_textpage_ocr(language=lang_str, dpi=dpi, full=True)
        except Exception as ocr_err:
            logger.debug("OCR with %s failed (%s); trying fallback language 'eng'", lang_str, ocr_err)
            tp = page.get_textpage_ocr(language="eng", dpi=dpi, full=True)

        page_dict = page.get_text("dict", textpage=tp)
        blocks = page_dict.get("blocks", [])
        added = 0

        for block in blocks:
            if block.get("type") != 0:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            b_rect = fitz.Rect(bbox)
            lines = block.get("lines", [])
            raw_text = " ".join("".join(s.get("text", "") for s in ln.get("spans", [])) for ln in lines).strip()
            cleaned_text = clean_xml_string(raw_text)

            if not cleaned_text or is_garbage_or_symbol_glyph(cleaned_text, default_font):
                continue

            left, top, w, h = geom.to_pptx_coords(b_rect.x0, b_rect.y0, b_rect.x1, b_rect.y1)
            tx_box = slide.shapes.add_textbox(left, top, w, h)
            tf = tx_box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = cleaned_text
            p.font.name = normalize_font_name("", default_font)
            p.font.size = Pt(11)
            added += 1

        if added > 0:
            logger.info("OCR successfully added %d text boxes to page %d", added, page.number + 1)
            return True
    except Exception as exc:
        logger.debug("PyMuPDF OCR unavailable or failed on page %d: %s", page.number + 1, exc)

    return False
