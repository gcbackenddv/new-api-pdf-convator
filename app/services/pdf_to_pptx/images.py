import io
import logging
import math
import re
from typing import Any
import fitz
from PIL import Image

from app.services.pdf_to_pptx.coordinates import SlideGeometry

logger = logging.getLogger(__name__)


def _get_image_clips(page: fitz.Page) -> dict[str, fitz.Rect]:
    """Extracts explicit clipping rectangles for images defined in PDF content streams.

    Finds the nearest preceding `re W* n` (or `re W n`) clipping operator before each `/Do` image invocation.
    """
    clips: dict[str, fitz.Rect] = {}
    try:
        contents = page.read_contents().decode("latin1", errors="ignore")
    except Exception:
        return clips

    do_pattern = re.compile(r"/([A-Za-z0-9_-]+)\s+Do")
    re_pattern = re.compile(r"([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+re\s+W\*?\s+n")

    for m in do_pattern.finditer(contents):
        im_name = m.group(1)
        do_pos = m.start()
        # Look backwards up to 600 characters for the enclosing clip operator
        chunk = contents[max(0, do_pos - 600) : do_pos]
        re_matches = list(re_pattern.finditer(chunk))
        if re_matches:
            last_re = re_matches[-1]
            x_str, y_str, w_str, h_str = last_re.groups()
            try:
                x, y, w, h = float(x_str), float(y_str), float(w_str), float(h_str)
                top = page.rect.height - (y + h)
                bottom = page.rect.height - y
                clips[im_name] = fitz.Rect(x, top, x + w, bottom)
            except Exception:
                pass
    return clips


def _prepare_image_stream(raw_bytes: bytes, ext: str) -> io.BytesIO | None:
    """Prepares image stream for python-pptx.

    Avoids re-encoding clean JPEG/PNG images unnecessarily to conserve CPU and preserve quality.
    Converts CMYK or non-standard color modes safely.
    """
    clean_ext = ext.lower().strip(".")
    try:
        # Fast path: If already standard JPEG or PNG, check mode without re-compressing
        if clean_ext in ("jpeg", "jpg"):
            with Image.open(io.BytesIO(raw_bytes)) as img:
                if img.mode == "RGB":
                    return io.BytesIO(raw_bytes)
                if img.mode == "CMYK":
                    converted = img.convert("RGB")
                    out = io.BytesIO()
                    converted.save(out, format="JPEG", quality=92)
                    out.seek(0)
                    return out

        if clean_ext == "png":
            with Image.open(io.BytesIO(raw_bytes)) as img:
                if img.mode in ("RGB", "RGBA"):
                    return io.BytesIO(raw_bytes)

        # General path for other formats, palettes, transparency
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
                target_fmt = "PNG" if clean_ext in ("png", "webp", "gif") else "JPEG"
                if target_fmt == "JPEG" and img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(out_buf, format=target_fmt, quality=92)
            out_buf.seek(0)
            return out_buf
    except Exception as exc:
        logger.debug("Image encoding fallback to raw bytes: %s", exc)
        return io.BytesIO(raw_bytes)


def extract_and_add_images(
    doc: fitz.Document,
    page: fitz.Page,
    slide: Any,
    geom: SlideGeometry,
    dpi: int = 150,
) -> int:
    """Extracts embedded images individually and places them on the PPT slide with rotation, transparency (smask), and coordinate fidelity."""
    try:
        images_info = page.get_image_info(xrefs=True)
    except Exception as exc:
        logger.warning("Could not read image info on page %d: %s", page.number + 1, exc)
        return 0

    if not images_info:
        return 0

    added = 0
    seen_rects: set[tuple[int, int, int, int]] = set()

    clips = _get_image_clips(page)
    name_map: dict[int, str] = {}
    try:
        for img in page.get_images():
            name_map[img[0]] = img[7]
    except Exception:
        pass

    for info in images_info:
        bbox = info.get("bbox")
        if not bbox or len(bbox) != 4:
            continue

        orig_rect = fitz.Rect(bbox)
        if orig_rect.width <= 2.0 or orig_rect.height <= 2.0:
            continue

        xref = info.get("xref", 0)
        im_name = name_map.get(xref, "")
        clip_rect = clips.get(im_name)
        vis_rect = fitz.Rect(orig_rect)

        if clip_rect:
            # Check if clip is not trivial full-page
            is_full_page = (
                clip_rect.width >= page.rect.width * 0.98
                and clip_rect.height >= page.rect.height * 0.98
            )
            if not is_full_page:
                intersection = orig_rect & clip_rect
                if intersection.width > 2.0 and intersection.height > 2.0:
                    vis_rect = intersection

        # Prevent exact duplicate image overlap
        coord_key = (int(vis_rect.x0), int(vis_rect.y0), int(vis_rect.x1), int(vis_rect.y1))
        if coord_key in seen_rects:
            continue
        seen_rects.add(coord_key)

        img_buf: io.BytesIO | None = None

        try:
            if xref > 0:
                extracted = doc.extract_image(xref)
                smask = extracted.get("smask", 0) if extracted else 0

                # Handle PDF soft masks (transparency channel stored separately in PDF)
                if smask > 0:
                    try:
                        pix_base = fitz.Pixmap(doc, xref)
                        if pix_base.colorspace and pix_base.colorspace.n != 3:
                            pix_base = fitz.Pixmap(fitz.csRGB, pix_base)
                        mask = fitz.Pixmap(doc, smask)
                        pix_rgba = fitz.Pixmap(pix_base, mask)
                        img_buf = io.BytesIO(pix_rgba.tobytes("png"))
                        del pix_base, mask, pix_rgba
                    except Exception as mask_exc:
                        logger.debug("Failed applying smask %d for xref %d: %s", smask, xref, mask_exc)

                if img_buf is None and extracted and extracted.get("image"):
                    img_buf = _prepare_image_stream(extracted["image"], extracted.get("ext", "png"))

            if img_buf is None:
                # Fallback for inline images or non-extractable xrefs: clip pixmap
                pix = page.get_pixmap(clip=vis_rect, dpi=dpi)
                img_buf = io.BytesIO(pix.tobytes("png"))
                del pix
                orig_rect = vis_rect

            # If image has a restrictive clip path, crop the image in PIL so it matches visible area
            if img_buf is not None and (
                (orig_rect.width - vis_rect.width > 1.0)
                or (orig_rect.height - vis_rect.height > 1.0)
                or (abs(orig_rect.x0 - vis_rect.x0) > 1.0)
                or (abs(orig_rect.y0 - vis_rect.y0) > 1.0)
            ):
                try:
                    img_buf.seek(0)
                    with Image.open(img_buf) as pil_img:
                        rx0 = max(0.0, min(1.0, (vis_rect.x0 - orig_rect.x0) / orig_rect.width))
                        ry0 = max(0.0, min(1.0, (vis_rect.y0 - orig_rect.y0) / orig_rect.height))
                        rx1 = max(0.0, min(1.0, (vis_rect.x1 - orig_rect.x0) / orig_rect.width))
                        ry1 = max(0.0, min(1.0, (vis_rect.y1 - orig_rect.y0) / orig_rect.height))

                        c_box = (
                            int(rx0 * pil_img.width),
                            int(ry0 * pil_img.height),
                            int(rx1 * pil_img.width),
                            int(ry1 * pil_img.height),
                        )
                        if c_box[2] > c_box[0] and c_box[3] > c_box[1]:
                            cropped = pil_img.crop(c_box)
                            cropped_buf = io.BytesIO()
                            fmt = "PNG" if cropped.mode in ("RGBA", "LA", "P") else "JPEG"
                            cropped.save(cropped_buf, format=fmt, quality=92)
                            cropped_buf.seek(0)
                            img_buf.close()
                            img_buf = cropped_buf
                except Exception as crop_exc:
                    logger.debug("Failed cropping image to clip rect: %s", crop_exc)

            if img_buf is not None:
                left, top, width, height = geom.to_pptx_coords(vis_rect.x0, vis_rect.y0, vis_rect.x1, vis_rect.y1)
                pic = slide.shapes.add_picture(img_buf, left, top, width, height)

                # Check for rotation in the image transform matrix
                transform = info.get("transform")
                if transform and len(transform) == 6:
                    a, b = transform[0], transform[1]
                    if abs(b) > 0.05:
                        angle_deg = math.degrees(math.atan2(b, a))
                        if abs(angle_deg) > 1.0:
                            pic.rotation = angle_deg

                added += 1
        except Exception as exc:
            logger.debug("Could not add image xref %d on page %d: %s", xref, page.number + 1, exc)
        finally:
            if img_buf is not None:
                img_buf.close()

    logger.debug("Added %d independent images to slide %d", added, page.number + 1)
    return added
