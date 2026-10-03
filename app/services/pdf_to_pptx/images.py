import io
import logging
from typing import Any
import fitz
from PIL import Image
from app.services.pdf_to_pptx.coordinates import SlideGeometry

logger = logging.getLogger(__name__)


def _prepare_image_stream(raw_bytes: bytes, ext: str) -> io.BytesIO | None:
    """Prepares image stream for python-pptx, handling CMYK conversion and transparency."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            out_buf = io.BytesIO()
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img.save(out_buf, format="PNG")
            elif img.mode == "CMYK":
                converted = img.convert("RGB")
                converted.save(out_buf, format="JPEG", quality=92)
            elif img.mode not in ("RGB", "L"):
                converted = img.convert("RGB")
                converted.save(out_buf, format="JPEG", quality=92)
            else:
                target_format = "PNG" if ext.lower() in ("png", "webp", "gif") else "JPEG"
                if target_format == "JPEG" and img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(out_buf, format=target_format, quality=92)
            out_buf.seek(0)
            return out_buf
    except Exception as exc:
        logger.debug("Image encoding fallback: %s", exc)
        return io.BytesIO(raw_bytes)


def extract_and_add_images(
    doc: fitz.Document,
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
) -> int:
    """Extract embedded images individually and place them on the PPT slide."""
    try:
        images_info = page.get_image_info(xrefs=True)
    except Exception as exc:
        logger.warning("Could not read image info on page %d: %s", page.number + 1, exc)
        return 0

    if not images_info:
        return 0

    added = 0
    seen_rects: set[tuple[int, int, int, int]] = set()

    for info in images_info:
        bbox = info.get("bbox")
        if not bbox or len(bbox) != 4:
            continue

        rect = fitz.Rect(bbox)
        if rect.width <= 2.0 or rect.height <= 2.0:
            continue

        # Prevent exact duplicate image overlap
        coord_key = (int(rect.x0), int(rect.y0), int(rect.x1), int(rect.y1))
        if coord_key in seen_rects:
            continue
        seen_rects.add(coord_key)

        xref = info.get("xref", 0)
        img_buf: io.BytesIO | None = None

        try:
            if xref > 0:
                extracted = doc.extract_image(xref)
                if extracted and extracted.get("image"):
                    img_buf = _prepare_image_stream(extracted["image"], extracted.get("ext", "png"))

            if img_buf is None:
                # Fallback for inline images or non-extractable xrefs: clip pixmap
                pix = page.get_pixmap(clip=rect, dpi=150)
                img_buf = io.BytesIO(pix.tobytes("png"))

            if img_buf is not None:
                left, top, width, height = geom.to_pptx_coords(rect.x0, rect.y0, rect.x1, rect.y1)
                slide.shapes.add_picture(img_buf, left, top, width, height)
                added += 1
        except Exception as exc:
            logger.debug("Could not add image xref %d on page %d: %s", xref, page.number + 1, exc)
        finally:
            if img_buf is not None:
                img_buf.close()

    logger.debug("Added %d independent images to slide %d", added, page.number + 1)
    return added
