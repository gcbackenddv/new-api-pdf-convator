"""Make a PDF searchable by adding an invisible OCR text layer."""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf as fitz

from app.config import get_settings
from .ocr import (
    OCRProcessingError,
    OCRUnavailableError,
    ocr_image,
    ocr_image_words,
    page_has_text,
    ocr_available,
    resolve_ocr_language,
)
from .renderer import render_page_to_image
from .validator import validate_pdf
from .deskew import detect_skew, deskew_image
from .orientation import detect_orientation

logger = logging.getLogger(__name__)

_OCR_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _get_font_for_word(
    word: str,
    page: fitz.Page,
    font_paths: tuple[str, ...],
    font_cache: dict[str, fitz.Font],
    registered_fonts: dict[str, str],
) -> tuple[str, fitz.Font]:
    builtin_font = font_cache["helv"]
    if all(builtin_font.has_glyph(ord(char)) for char in word):
        return "helv", builtin_font

    for path in font_paths:
        if path not in font_cache:
            if not Path(path).is_file():
                continue
            try:
                font_cache[path] = fitz.Font(fontfile=path)
            except Exception:
                logger.warning("Unable to load OCR text-layer font: %s", path)
                continue
        font = font_cache[path]
        if all(font.has_glyph(ord(char)) for char in word):
            if path not in registered_fonts:
                font_name = f"ocrfont{len(registered_fonts)}"
                page.insert_font(fontname=font_name, fontfile=path)
                registered_fonts[path] = font_name
            return registered_fonts[path], font

    return "helv", builtin_font


def _insert_word_boxes(
    page: fitz.Page,
    words: list[dict[str, object]],
    img_width: int,
    img_height: int,
    font_path: str = "",
) -> int:
    """
    Insert invisible text directly at the exact (x, y) coordinates of each word.
    Coordinates are scaled from the rendered image resolution to the PDF page size.
    """
    if not words:
        return 0

    page_rect = page.rect
    scale_x = page_rect.width / max(1, img_width)
    scale_y = page_rect.height / max(1, img_height)

    builtin_font = fitz.Font("helv")
    font_cache: dict[str, fitz.Font] = {"helv": builtin_font}
    registered_fonts: dict[str, str] = {}
    font_paths = tuple(dict.fromkeys(path for path in (font_path, *_OCR_FONT_CANDIDATES) if path))

    inserted = 0
    for w in words:
        text = str(w.get("text", "")).strip()
        if not text:
            continue

        box_x = float(w["left"]) * scale_x
        box_y = float(w["top"]) * scale_y
        box_w = float(w["width"]) * scale_x
        box_h = float(w["height"]) * scale_y

        font_name, font = _get_font_for_word(
            text, page, font_paths, font_cache, registered_fonts
        )

        fontsize = max(3.0, min(box_h * 0.9, 72.0))
        measured_w = font.text_length(text, fontsize=fontsize)
        if measured_w > 0 and box_w > 0:
            scale_factor = box_w / measured_w
            if 0.5 <= scale_factor <= 1.5:
                fontsize *= scale_factor
                fontsize = max(3.0, min(fontsize, 72.0))

        y_pos = min(page_rect.y1 - 1, box_y + box_h * 0.85)
        x_pos = max(page_rect.x0, min(page_rect.x1 - 5, box_x))

        try:
            page.insert_text(
                (x_pos, y_pos),
                text,
                fontsize=fontsize,
                fontname=font_name,
                render_mode=3,  # 3 = invisible text
            )
            inserted += 1
        except Exception as exc:
            logger.debug("Failed inserting invisible word '%s': %s", text, exc)

    return inserted


def make_searchable(
    src: Path,
    dst: Path,
    *,
    lang: str | None = None,
    force_ocr: bool = False,
    deskew: bool = False,
    auto_rotate: bool = False,
) -> dict:
    """
    Produce a new PDF with an invisible OCR text layer matching exact word positions.
    Preserves original PDF pages, colors, vector graphics, and images.
    """
    validate_pdf(src)
    settings = get_settings()
    requested_lang = (lang or "").strip().lower()
    doc = fitz.open(src)
    ocr_pages = 0
    skipped = 0
    words_recognized = 0
    ocr_ready = False

    try:
        if force_ocr:
            target_check = None if requested_lang in ("", "auto") else lang
            if not ocr_available(target_check):
                target_name = lang or "auto"
                raise OCRUnavailableError(
                    f"Tesseract OCR or language data '{target_name}' is not available on this server."
                )
            ocr_ready = True

        for i in range(doc.page_count):
            page = doc[i]
            if not force_ocr and page_has_text(page):
                skipped += 1
                continue
            if not ocr_ready:
                target_check = None if requested_lang in ("", "auto") else lang
                if not ocr_available(target_check):
                    target_name = lang or "auto"
                    raise OCRUnavailableError(
                        f"Tesseract OCR or language data '{target_name}' is not available on this server."
                    )
                ocr_ready = True

            img = render_page_to_image(
                doc,
                i,
                dpi=min(settings.OCR_DPI, settings.MAX_RENDER_DPI),
            )

            if auto_rotate:
                angle, conf = detect_orientation(img)
                if angle in (90, 180, 270) and conf >= 0.5:
                    page.set_rotation((page.rotation + angle) % 360)
                    img = img.rotate(angle, expand=True)

            if deskew:
                skew_angle, conf = detect_skew(img)
                if abs(skew_angle) >= 0.5 and conf >= 0.4:
                    img = deskew_image(img, skew_angle)

            # Extract word bounding boxes from Tesseract
            words = ocr_image_words(img, lang=lang)
            if not words:
                # Fallback to plain string extraction if bounding boxes were empty
                fallback_text = ocr_image(img, lang=lang)
                if fallback_text:
                    words = [{"text": w, "left": 10, "top": 10 + idx * 15, "width": 50, "height": 12}
                             for idx, w in enumerate(fallback_text.split())]

            word_count = len(words)
            words_recognized += word_count

            _insert_word_boxes(page, words, img.width, img.height, settings.OCR_FONT_PATH)
            ocr_pages += 1

        if force_ocr and words_recognized < settings.OCR_MIN_WORDS:
            raise OCRProcessingError(
                "OCR completed but recognized too little text to create a searchable PDF. "
                "Check the scan quality and selected OCR language."
            )

        doc.save(dst, garbage=4, deflate=True)
        return {
            "pages_total": doc.page_count,
            "pages_ocrd": ocr_pages,
            "pages_skipped": skipped,
            "words_recognized": words_recognized,
        }
    finally:
        doc.close()

