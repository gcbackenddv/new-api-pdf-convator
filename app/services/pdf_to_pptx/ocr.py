import logging
from typing import Any
import fitz
from pptx.util import Pt
from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pdf_to_pptx.fonts import normalize_font_name

logger = logging.getLogger(__name__)


def is_scanned_page(page: fitz.Page) -> bool:
    """Determine if a page is a scanned document.

    A page is considered scanned if it contains NO extractable digital text
    and is dominated by an image (like a flatbed scan).
    """
    try:
        text = page.get_text().strip()
        # If the page contains any digital text, treat as a digital page
        if len(text) > 0:
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
                # Large image covering >= 50% of the page with 0 text indicates a scanned document
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
) -> bool:
    """Attempt OCR using PaddleOCR or PyMuPDF OCR. Returns True if editable text was added."""
    # 1. Attempt PaddleOCR if installed
    try:
        from paddleocr import PaddleOCR  # type: ignore

        lang_code = "en"
        for candidate in languages.split(","):
            c = candidate.strip().lower()
            if c in ("ben", "bengali", "bn"):
                lang_code = "ta" if c == "ta" else "en"
            elif c in ("eng", "en", "english"):
                lang_code = "en"

        ocr_engine = PaddleOCR(use_angle_cls=True, lang=lang_code, show_log=False)
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")

        ocr_res = ocr_engine.ocr(img_bytes, cls=True)
        if ocr_res and ocr_res[0]:
            scale_x = page.rect.width / pix.width
            scale_y = page.rect.height / pix.height
            added = 0
            for line_data in ocr_res[0]:
                coords, (text_str, conf) = line_data
                if not text_str.strip():
                    continue
                xs = [pt[0] * scale_x for pt in coords]
                ys = [pt[1] * scale_y for pt in coords]
                x0, x1 = min(xs), max(xs)
                y0, y1 = min(ys), max(ys)

                left, top, w, h = geom.to_pptx_coords(x0, y0, x1, y1)
                tx_box = slide.shapes.add_textbox(left, top, w, h)
                tf = tx_box.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = text_str
                p.font.name = normalize_font_name("", default_font)
                p.font.size = Pt(12)
                added += 1

            if added > 0:
                logger.info("PaddleOCR successfully added %d text boxes to page %d", added, page.number + 1)
                return True
    except (ImportError, Exception) as exc:
        logger.debug("PaddleOCR not available or failed on page %d: %s", page.number + 1, exc)

    # 2. Attempt PyMuPDF Tesseract OCR integration
    try:
        lang_str = languages.replace(",", "+").replace("ben", "ben").replace("eng", "eng")
        tp = page.get_textpage_ocr(language=lang_str, dpi=150, full=True)
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
            full_text = " ".join("".join(s.get("text", "") for s in ln.get("spans", [])) for ln in lines).strip()
            if not full_text:
                continue

            left, top, w, h = geom.to_pptx_coords(b_rect.x0, b_rect.y0, b_rect.x1, b_rect.y1)
            tx_box = slide.shapes.add_textbox(left, top, w, h)
            tf = tx_box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = full_text
            p.font.name = default_font
            p.font.size = Pt(12)
            added += 1

        if added > 0:
            logger.info("PyMuPDF OCR added %d text boxes to page %d", added, page.number + 1)
            return True
    except Exception as exc:
        logger.debug("PyMuPDF OCR not available or failed on page %d: %s", page.number + 1, exc)

    return False
