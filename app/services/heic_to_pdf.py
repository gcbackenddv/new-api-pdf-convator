import logging
import time
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
import pymupdf
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()
logger = logging.getLogger(__name__)

PAPER = {"a4": (595.0, 842.0), "letter": (612.0, 792.0)}  # points, portrait
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
_ENCODERS = {"jpeg": ("JPEG", "jpg"), "lossless": ("PNG", "png")}


class HeicToPdfError(Exception):
    """Client-safe failure. The router converts it to an HTTPException."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class HeicToPdfResult:
    pdf_path: Path
    page_count: int
    size_bytes: int


def _check_heif_header(path: Path) -> None:
    with path.open("rb") as fh:
        head = fh.read(12)
    if len(head) < 12 or head[4:8] != b"ftyp" or head[8:12] not in _HEIF_BRANDS:
        raise HeicToPdfError("Only HEIC/HEIF files are supported.", 400)


def _prepare_image(
    src: Path, dst: Path, name: str, *, pil_format: str, quality: int, max_pixels: int
) -> tuple[int, int]:
    """Decode one HEIC, fix orientation, flatten alpha, write a temp file, return pixel size."""
    try:
        with Image.open(src) as img:
            if img.width * img.height > max_pixels:  # header-only check, nothing decoded yet
                raise HeicToPdfError(f"Image exceeds the maximum allowed resolution: {name}", 413)
            img.load()
            img = ImageOps.exif_transpose(img)  # applies camera rotation/mirroring
            if img.mode in ("RGBA", "LA") or "transparency" in img.info:
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")
                flat.paste(rgba, mask=rgba.getchannel("A"))
                rgba.close()
                img = flat
            elif img.mode != "RGB":
                img = img.convert("RGB")
            size = img.size
            if pil_format == "JPEG":
                img.save(dst, format="JPEG", quality=quality, subsampling=0)
            else:
                img.save(dst, format="PNG")
            img.close()
            return size
    except HeicToPdfError:
        raise
    except Exception as exc:
        logger.warning("Could not decode HEIC '%s': %s", name, exc)
        raise HeicToPdfError(f"Unable to decode HEIC image: {name}", 422) from exc


def _rects(px_w: int, px_h: int, dpi: int, page_size: str) -> tuple[fitz.Rect, fitz.Rect]:
    if page_size in PAPER:
        bw, bh = PAPER[page_size]
        pw, ph = (bw, bh) if px_h >= px_w else (bh, bw)  # rotate paper to match image
        scale = min(pw / px_w, ph / px_h)  # fit, never stretch or crop
        w, h = px_w * scale, px_h * scale
        x, y = (pw - w) / 2, (ph - h) / 2
        return fitz.Rect(0, 0, pw, ph), fitz.Rect(x, y, x + w, y + h)
    w, h = px_w * 72.0 / dpi, px_h * 72.0 / dpi  # auto: page = image
    return fitz.Rect(0, 0, w, h), fitz.Rect(0, 0, w, h)


def convert_heic_to_pdf(
    items: list[tuple[Path, str]],
    work_dir: Path,
    *,
    dpi: int,
    quality: int,
    page_size: str,
    compression: str,
    max_pixels: int,
) -> HeicToPdfResult:
    """Build one PDF with one page per image, in the order given.

    `items` is a list of (stored path, sanitized display name).
    """
    if not items:
        raise HeicToPdfError("No HEIC files were uploaded.", 400)
    pil_format, ext = _ENCODERS[compression]
    started = time.perf_counter()
    logger.info(
        "HEIC to PDF started: images=%d dpi=%d page_size=%s compression=%s",
        len(items), dpi, page_size, compression,
    )

    pdf_path = work_dir / "converted.pdf"
    doc = fitz.open()
    try:
        for index, (src, name) in enumerate(items, start=1):
            _check_heif_header(src)
            tmp = work_dir / f"page-{index:03d}.{ext}"
            try:
                px_w, px_h = _prepare_image(
                    src, tmp, name, pil_format=pil_format, quality=quality, max_pixels=max_pixels
                )
                page_rect, image_rect = _rects(px_w, px_h, dpi, page_size)
                page = doc.new_page(width=page_rect.width, height=page_rect.height)
                page.insert_image(image_rect, filename=str(tmp))
            except HeicToPdfError:
                raise
            except Exception as exc:
                logger.exception("Failed to add image %d to PDF", index)
                raise HeicToPdfError("Unable to generate PDF.", 500) from exc
            finally:
                tmp.unlink(missing_ok=True)  # one decoded image alive at a time
                src.unlink(missing_ok=True)  # input no longer needed
            logger.info("Added image %d/%d", index, len(items))
        try:
            doc.save(pdf_path, garbage=3, deflate=True)
        except Exception as exc:
            logger.exception("Saving PDF failed")
            raise HeicToPdfError("Unable to generate PDF.", 500) from exc
    finally:
        doc.close()

    size = pdf_path.stat().st_size
    logger.info(
        "HEIC to PDF completed: pages=%d bytes=%d seconds=%.2f",
        len(items), size, time.perf_counter() - started,
    )
    return HeicToPdfResult(pdf_path, len(items), size)