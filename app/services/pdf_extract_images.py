"""PDF embedded-image extraction + ZIP creation.

Pipeline: validate -> stream upload to temp file -> open PDF -> collect image
references -> write image bytes (original or converted) -> ZIP -> (caller
streams ZIP, then cleans up).

Duplicate policy: every image object (xref) is extracted once, under the first
page that references it; later references are skipped.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pymupdf
from PIL import Image

from app.config import settings as config

try:  # HEIC read/write support is optional at import time
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HEIF_AVAILABLE = False

logger = logging.getLogger(__name__)

# --- constants ---------------------------------------------------------------
MIB = 1024 * 1024
PDF_SIGNATURE = b"%PDF-"
PDF_SIGNATURE_WINDOW = 1024          # PDF spec allows the header within the first 1 KiB
UPLOAD_CHUNK_SIZE = MIB
SOURCE_FILENAME = "source.pdf"
IMAGES_DIRNAME = "images"
ZIP_FILENAME = "extracted_images.zip"
ZIP_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)   # deterministic archives
ZIP_FILE_MODE = 0o644 << 16
ZIP_COPY_CHUNK = MIB

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_EXTENSION_RE = re.compile(r"^[a-z0-9]{1,5}$")
_EXTENSION_ALIASES = {"jpeg": "jpg", "jpx": "jp2"}
_FALLBACK_EXTENSION = "bin"
_ACCEPTED_CONTENT_TYPES = frozenset({
    "application/pdf", "application/x-pdf", "application/acrobat",
    "text/pdf", "text/x-pdf", "application/octet-stream",
})
_PILLOW_FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "heic": "HEIF"}
_WHITE = (255, 255, 255)


class OutputFormat(str, Enum):
    """User-selectable output format. ``jpeg`` and ``jpg`` are equivalent."""

    ORIGINAL = "original"
    JPG = "jpg"
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    HEIC = "heic"

    @property
    def extension(self) -> str | None:
        """File extension to produce, or ``None`` to keep the original format."""
        if self is OutputFormat.ORIGINAL:
            return None
        return "jpg" if self is OutputFormat.JPEG else self.value


# --- exceptions (messages are client-safe) ------------------------------------
class PDFExtractionError(Exception):
    """Base class; also used for generic extraction failures."""


class PDFValidationError(PDFExtractionError):
    """The upload itself is invalid (e.g. empty)."""


class UnsupportedMediaTypeError(PDFValidationError):
    """Extension / MIME type / signature say this is not a PDF."""


class FileTooLargeError(PDFValidationError):
    """Upload exceeds the configured maximum size."""


class UnsupportedPDFError(PDFExtractionError):
    """Valid PDF we refuse to process (e.g. password protected)."""


class NoImagesFoundError(PDFExtractionError):
    """The PDF has no embedded images."""


class ResourceLimitError(PDFExtractionError):
    """A configured resource limit was exceeded."""


class ExtractionTimeoutError(ResourceLimitError):
    """The cooperative deadline expired."""


class OutputFormatUnavailableError(PDFExtractionError):
    """The requested output format can't be produced on this server."""


# --- settings / data classes --------------------------------------------------
@dataclass(frozen=True)
class ExtractionSettings:
    output_root: Path
    max_pdf_bytes: int
    timeout_seconds: float
    max_pages: int
    max_images: int
    max_image_pixels: int
    max_output_bytes: int
    job_ttl_seconds: int
    apply_soft_masks: bool
    jpeg_quality: int = 95
    png_quality: int = 95
    webp_quality: int = 95
    heic_quality: int = 90

    @classmethod
    def from_config(cls) -> "ExtractionSettings":
        return cls(
            output_root=config.OUTPUT_DIR / config.PDF_IMAGE_EXTRACT_DIRNAME,
            max_pdf_bytes=config.MAX_PDF_SIZE_MB * MIB,
            timeout_seconds=config.PDF_IMAGE_EXTRACT_TIMEOUT,
            max_pages=config.PDF_IMAGE_MAX_PAGES,
            max_images=config.PDF_IMAGE_MAX_IMAGES,
            max_image_pixels=config.PDF_IMAGE_MAX_PIXELS,
            max_output_bytes=config.PDF_IMAGE_MAX_OUTPUT_MB * MIB,
            job_ttl_seconds=config.PDF_IMAGE_JOB_TTL_SECONDS,
            apply_soft_masks=config.PDF_IMAGE_APPLY_SOFT_MASKS,
            jpeg_quality=config.PDF_IMAGE_JPEG_QUALITY,
            png_quality=config.PDF_IMAGE_PNG_QUALITY,
            webp_quality=config.PDF_IMAGE_WEBP_QUALITY,
            heic_quality=config.PDF_IMAGE_HEIC_QUALITY,
        )


@dataclass(frozen=True)
class ExtractionJob:
    root: Path

    @property
    def job_id(self) -> str:
        return self.root.name

    @property
    def source_path(self) -> Path:
        return self.root / SOURCE_FILENAME

    @property
    def images_dir(self) -> Path:
        return self.root / IMAGES_DIRNAME

    @property
    def zip_path(self) -> Path:
        return self.root / ZIP_FILENAME


@dataclass(frozen=True)
class ImageRef:
    page_number: int   # 1-based
    xref: int
    smask: int
    width: int
    height: int


@dataclass(frozen=True)
class ExtractionResult:
    zip_path: Path
    page_count: int
    images_found: int          # image references across all pages
    images_extracted: int
    duplicates_skipped: int
    images_skipped: int        # oversized, undecodable or failed conversion
    zip_size_bytes: int


# --- logging helper -------------------------------------------------------------
def _log(level: int, event: str, **fields: object) -> None:
    """Structured key=value logging. Never pass document/image content."""
    logger.log(level, "%s %s", event, " ".join(f"{k}={v}" for k, v in fields.items()))


# --- validation -------------------------------------------------------------------
def validate_output_format(output_format: OutputFormat) -> None:
    """Fail fast, before any upload is processed."""
    if output_format is OutputFormat.HEIC and not _HEIF_AVAILABLE:
        raise OutputFormatUnavailableError("HEIC output is not available on this server.")


def validate_upload_metadata(
    filename: str | None,
    content_type: str | None,
    size: int | None,
    settings: ExtractionSettings,
) -> None:
    """Cheap pre-checks. The authoritative check is the signature in save_upload."""
    if Path(filename or "").suffix.lower() != ".pdf":
        raise UnsupportedMediaTypeError("Only files with a .pdf extension are accepted.")
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime and mime not in _ACCEPTED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError("The uploaded file is not declared as a PDF.")
    if size is not None and size > settings.max_pdf_bytes:
        raise FileTooLargeError(_too_large_message(settings))


def _too_large_message(settings: ExtractionSettings) -> str:
    return f"The PDF exceeds the maximum allowed size of {settings.max_pdf_bytes / MIB:.0f} MB."


# --- job directory lifecycle -------------------------------------------------------
def create_job(settings: ExtractionSettings) -> ExtractionJob:
    purge_stale_jobs(settings)
    root = settings.output_root / uuid.uuid4().hex
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    (root / IMAGES_DIRNAME).mkdir(mode=0o700)
    return ExtractionJob(root=root)


def cleanup_job(job_root: Path) -> None:
    """Remove a job directory. Refuses anything that isn't a UUID-named dir."""
    if not _JOB_ID_RE.match(job_root.name):
        _log(logging.ERROR, "pdf_image_extraction.cleanup_refused", reason="unexpected_name")
        return
    try:
        shutil.rmtree(job_root)
        _log(logging.INFO, "pdf_image_extraction.cleaned", job_id=job_root.name)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("pdf_image_extraction.cleanup_failed job_id=%s", job_root.name)


def purge_stale_jobs(settings: ExtractionSettings) -> None:
    """Safety net for jobs orphaned by crashes or client disconnects."""
    try:
        entries = list(settings.output_root.iterdir())
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("pdf_image_extraction.purge_failed")
        return
    cutoff = time.time() - settings.job_ttl_seconds
    for entry in entries:
        try:
            if _JOB_ID_RE.match(entry.name) and entry.is_dir() and entry.stat().st_mtime < cutoff:
                cleanup_job(entry)
        except OSError:
            logger.exception("pdf_image_extraction.purge_entry_failed")


# --- upload ----------------------------------------------------------------------
def save_upload(stream: BinaryIO, job: ExtractionJob, settings: ExtractionSettings) -> int:
    """Stream the upload to disk, enforcing signature and size limits."""
    total = 0
    checked_signature = False
    fd = os.open(job.source_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        while chunk := stream.read(UPLOAD_CHUNK_SIZE):
            if not checked_signature:
                if PDF_SIGNATURE not in chunk[:PDF_SIGNATURE_WINDOW]:
                    raise UnsupportedMediaTypeError("The uploaded file is not a valid PDF.")
                checked_signature = True
            total += len(chunk)
            if total > settings.max_pdf_bytes:
                raise FileTooLargeError(_too_large_message(settings))
            out.write(chunk)
    if total == 0:
        raise PDFValidationError("The uploaded file is empty.")
    _log(logging.INFO, "pdf_image_extraction.validated", job_id=job.job_id, size_bytes=total)
    return total


# --- extraction ------------------------------------------------------------------
def extract_images_to_zip(
    job: ExtractionJob,
    settings: ExtractionSettings,
    output_format: OutputFormat = OutputFormat.ORIGINAL,
) -> ExtractionResult:
    """Extract embedded images from ``job.source_path`` into a ZIP."""
    started = time.monotonic()
    deadline = started + settings.timeout_seconds
    _log(logging.INFO, "pdf_image_extraction.started", job_id=job.job_id,
         output_format=output_format.value)
    try:
        with _open_pdf(job.source_path, settings) as doc:
            page_count = doc.page_count
            _log(logging.INFO, "pdf_image_extraction.pages", job_id=job.job_id, pages=page_count)

            refs, total_refs, duplicates = _collect_image_refs(doc, settings, deadline)
            _log(logging.INFO, "pdf_image_extraction.images_found", job_id=job.job_id,
                 references=total_refs, unique=len(refs), duplicates=duplicates)
            if not refs:
                raise NoImagesFoundError("No embedded images were found in the PDF.")

            names, skipped = _write_images(doc, refs, job, settings, deadline, output_format)
    except PDFExtractionError:
        _log(logging.WARNING, "pdf_image_extraction.failed", job_id=job.job_id)
        raise
    finally:
        job.source_path.unlink(missing_ok=True)  # the upload is no longer needed

    if not names:
        raise PDFExtractionError("Unable to extract images from the uploaded PDF.")

    _check_deadline(deadline)
    _build_zip(job, names)
    zip_size = job.zip_path.stat().st_size
    _log(logging.INFO, "pdf_image_extraction.completed", job_id=job.job_id,
         extracted=len(names), skipped=skipped, zip_bytes=zip_size,
         seconds=f"{time.monotonic() - started:.2f}")
    return ExtractionResult(
        zip_path=job.zip_path,
        page_count=page_count,
        images_found=total_refs,
        images_extracted=len(names),
        duplicates_skipped=duplicates,
        images_skipped=skipped,
        zip_size_bytes=zip_size,
    )


def _open_pdf(path: Path, settings: ExtractionSettings) -> pymupdf.Document:
    try:
        doc = pymupdf.open(str(path), filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several types for damaged input
        logger.warning("pdf_image_extraction.open_failed error_type=%s", type(exc).__name__)
        raise PDFExtractionError("The uploaded file is not a readable PDF (it may be corrupted).") from exc
    try:
        if doc.needs_pass:
            raise UnsupportedPDFError("Password-protected PDFs are not supported.")
        if not doc.is_pdf or doc.page_count == 0:
            raise PDFExtractionError("The uploaded file is not a readable PDF (it may be corrupted).")
        if doc.page_count > settings.max_pages:
            raise ResourceLimitError(f"The PDF has more than {settings.max_pages} pages.")
        if doc.is_repaired:
            logger.warning("pdf_image_extraction.pdf_was_repaired")
    except Exception:
        doc.close()
        raise
    return doc


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ExtractionTimeoutError("Image extraction exceeded the allowed processing time.")


def _collect_image_refs(
    doc: pymupdf.Document, settings: ExtractionSettings, deadline: float
) -> tuple[list[ImageRef], int, int]:
    """Return (unique refs in page order, total references, duplicates skipped)."""
    refs: list[ImageRef] = []
    seen: set[int] = set()
    total = duplicates = 0
    for page_index in range(doc.page_count):
        _check_deadline(deadline)
        try:
            # full=True also reports images nested in form XObjects.
            entries = doc.get_page_images(page_index, full=True)
        except Exception:
            logger.warning("pdf_image_extraction.page_unreadable page=%d", page_index + 1)
            continue
        for xref, smask, width, height, *_ in entries:
            if xref <= 0:
                continue
            total += 1
            if xref in seen:
                duplicates += 1
                continue
            seen.add(xref)
            if len(refs) >= settings.max_images:
                raise ResourceLimitError(f"The PDF contains more than {settings.max_images} images.")
            refs.append(ImageRef(page_index + 1, xref, smask, width, height))
    return refs, total, duplicates


def _write_images(
    doc: pymupdf.Document,
    refs: list[ImageRef],
    job: ExtractionJob,
    settings: ExtractionSettings,
    deadline: float,
    output_format: OutputFormat = OutputFormat.ORIGINAL,
) -> tuple[list[str], int]:
    names: list[str] = []
    skipped = 0
    per_page: Counter[int] = Counter()
    total_bytes = 0
    for ref in refs:
        _check_deadline(deadline)
        if ref.width * ref.height > settings.max_image_pixels:
            skipped += 1
            _log(logging.WARNING, "pdf_image_extraction.image_too_large",
                 job_id=job.job_id, page=ref.page_number, xref=ref.xref)
            continue
        try:
            data, ext = _read_image(doc, ref, settings.apply_soft_masks)
            data, ext = _apply_output_format(data, ext, output_format, settings)
        except Exception as exc:  # damaged object or failed conversion: skip, keep going
            skipped += 1
            _log(logging.WARNING, "pdf_image_extraction.image_unreadable", job_id=job.job_id,
                 page=ref.page_number, xref=ref.xref, error_type=type(exc).__name__)
            continue
        total_bytes += len(data)
        if total_bytes > settings.max_output_bytes:
            raise ResourceLimitError("The extracted images exceed the maximum allowed output size.")
        per_page[ref.page_number] += 1
        name = f"page-{ref.page_number:03d}-image-{per_page[ref.page_number]:03d}.{ext}"
        with open(job.images_dir / name, "xb") as fh:   # "x": never overwrite
            fh.write(data)
        names.append(name)
    _log(logging.INFO, "pdf_image_extraction.images_written", job_id=job.job_id,
         written=len(names), skipped=skipped, bytes=total_bytes)
    return names, skipped


def _read_image(doc: pymupdf.Document, ref: ImageRef, apply_soft_masks: bool) -> tuple[bytes, str]:
    info = doc.extract_image(ref.xref)
    if not info or not info.get("image"):
        raise PDFExtractionError("empty image object")
    data: bytes = info["image"]
    ext = _normalize_extension(info.get("ext"))
    smask = ref.smask or info.get("smask") or 0
    if apply_soft_masks and smask > 0:
        merged = _merge_soft_mask(doc, data, smask)
        if merged is not None:
            return merged, "png"
    return data, ext


def _normalize_extension(ext: str | None) -> str:
    """Allow-list the extension so library output can never inject path parts."""
    ext = (ext or "").lower()
    ext = _EXTENSION_ALIASES.get(ext, ext)
    return ext if _EXTENSION_RE.match(ext) else _FALLBACK_EXTENSION


def _merge_soft_mask(doc: pymupdf.Document, data: bytes, smask_xref: int) -> bytes | None:
    """Combine image + soft mask into an RGBA PNG; ``None`` means 'use raw bytes'."""
    try:
        base = pymupdf.Pixmap(data)
        if base.alpha:
            base = pymupdf.Pixmap(base, 0)                      # drop existing alpha
        if base.colorspace is not None and base.colorspace.n > 3:
            base = pymupdf.Pixmap(pymupdf.csRGB, base)          # CMYK -> RGB (PNG can't hold CMYK)
        mask_info = doc.extract_image(smask_xref)
        mask = pymupdf.Pixmap(mask_info["image"])
        if mask.colorspace is None or mask.colorspace.n != 1 or mask.alpha:
            mask = pymupdf.Pixmap(pymupdf.csGRAY, mask)
        if (mask.width, mask.height) != (base.width, base.height):
            return None
        return pymupdf.Pixmap(base, mask).tobytes("png")
    except Exception:
        logger.debug("pdf_image_extraction.soft_mask_merge_failed", exc_info=True)
        return None


# --- format conversion -----------------------------------------------------------
def _apply_output_format(
    data: bytes, ext: str, output_format: OutputFormat, settings: ExtractionSettings
) -> tuple[bytes, str]:
    target = output_format.extension
    if target is None or target == ext:
        return data, ext                      # keep original bytes untouched
    return _convert_image(data, target, settings), target


def _decode(data: bytes) -> Image.Image:
    try:
        img = Image.open(BytesIO(data))
        img.load()
        return img
    except Exception:
        # JPEG2000 and other exotic encodings: let MuPDF decode, then hand over as PNG.
        pix = pymupdf.Pixmap(data)
        if pix.colorspace is not None and pix.colorspace.n > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        img = Image.open(BytesIO(pix.tobytes("png")))
        img.load()
        return img


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _prepare_mode(img: Image.Image, target: str) -> Image.Image:
    """Convert to a pixel mode the target encoder handles correctly."""
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        if target == "jpg":                   # JPEG has no alpha: flatten onto white
            flat = Image.new("RGB", rgba.size, _WHITE)
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return rgba
    keep_gray = target in ("jpg", "png") and img.mode == "L"
    if keep_gray or img.mode == "RGB":
        return img
    return img.convert("RGB")                 # CMYK, palette, 1-bit, 16-bit, ...


def _save_options(target: str, settings: ExtractionSettings) -> dict[str, object]:
    if target == "jpg":
        return {"quality": settings.jpeg_quality, "optimize": True}
    if target == "png":
        # Pillow PNG uses compress_level (0=none/fastest … 9=max compression).
        # Map the 0-100 quality value inversely: higher quality → lower compression.
        compress_level = max(0, min(9, 9 - round(settings.png_quality / 100 * 9)))
        return {"compress_level": compress_level, "optimize": True}
    if target == "webp":
        return {"quality": settings.webp_quality, "method": 4}
    if target == "heic":
        return {"quality": settings.heic_quality}
    return {}


def _convert_image(data: bytes, target: str, settings: ExtractionSettings) -> bytes:
    img = _prepare_mode(_decode(data), target)
    out = BytesIO()
    img.save(out, format=_PILLOW_FORMATS[target], **_save_options(target, settings))
    return out.getvalue()


# --- ZIP -------------------------------------------------------------------------
def _build_zip(job: ExtractionJob, names: list[str]) -> None:
    """Create the archive from files on disk, streaming in chunks."""
    with zipfile.ZipFile(job.zip_path, mode="x", compression=zipfile.ZIP_STORED) as zf:
        for name in sorted(names):
            info = zipfile.ZipInfo(f"{IMAGES_DIRNAME}/{name}", date_time=ZIP_FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED   # images are already compressed
            info.external_attr = ZIP_FILE_MODE
            with open(job.images_dir / name, "rb") as src, zf.open(info, "w") as dst:
                shutil.copyfileobj(src, dst, ZIP_COPY_CHUNK)
    _log(logging.INFO, "pdf_image_extraction.zip_created", job_id=job.job_id, entries=len(names))