"""PDF flattening.

Pipeline: validate -> stream upload to temp file -> open PDF -> reject
encrypted/signed -> refresh widget appearances -> bake widgets/annotations
into page content -> strip active content -> save -> verify output.

The page content stays vector/text based: nothing is rendered to images.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pymupdf

from app.config import settings as config

logger = logging.getLogger(__name__)

# --- constants ---------------------------------------------------------------
MIB = 1024 * 1024
PDF_SIGNATURE = b"%PDF-"
PDF_SIGNATURE_WINDOW = 1024            # PDF spec allows the header within the first 1 KiB
UPLOAD_CHUNK_SIZE = MIB
INPUT_FILENAME = "input.pdf"
OUTPUT_FILENAME = "flattened.pdf"
SIGFLAGS_SIGNATURES_EXIST = 1          # AcroForm /SigFlags bit 1

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACCEPTED_CONTENT_TYPES = frozenset({
    "application/pdf", "application/x-pdf", "application/acrobat",
    "text/pdf", "text/x-pdf", "application/octet-stream",
})
# Link actions that can execute code or leave the document; URI/GoTo links stay.
_ACTIVE_ACTIONS = frozenset({"/JavaScript", "/Launch", "/SubmitForm", "/ImportData"})
# Annotation kinds that are not counted as "annotations to flatten".
_UNCOUNTED_ANNOT_TYPES = frozenset({
    pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_POPUP,
})
_CATALOG_KEYS_TO_REMOVE = ("AcroForm", "OpenAction", "AA")


# --- exceptions (messages are client-safe) ------------------------------------
class PDFFlattenError(Exception):
    """Base class; also used for generic flattening failures."""


class PDFValidationError(PDFFlattenError):
    """The upload itself is invalid (e.g. empty)."""


class UnsupportedMediaTypeError(PDFValidationError):
    """Extension / MIME type / signature say this is not a PDF."""


class FileTooLargeError(PDFValidationError):
    """Upload exceeds the configured maximum size."""


class PDFOpenError(PDFFlattenError):
    """The file can't be opened as a PDF (corrupted or malformed)."""


class PDFEncryptedError(PDFFlattenError):
    """The PDF is encrypted or password protected."""


class PDFSignatureError(PDFFlattenError):
    """The PDF is digitally signed and flattening would invalidate it."""


class ResourceLimitError(PDFFlattenError):
    """A configured resource limit was exceeded."""


class PDFTimeoutError(ResourceLimitError):
    """The cooperative deadline expired."""


# --- settings / data classes --------------------------------------------------
@dataclass(frozen=True)
class FlattenSettings:
    output_root: Path
    max_pdf_bytes: int
    timeout_seconds: float
    max_pages: int
    job_ttl_seconds: int
    allow_signed: bool
    flatten_forms: bool = True
    flatten_annotations: bool = True
    flatten_stamps: bool = True
    full_flatten: bool = False
    dpi: int = 150

    @classmethod
    def from_config(
        cls,
        flatten_forms: bool = True,
        flatten_annotations: bool = True,
        flatten_stamps: bool = True,
        full_flatten: bool = False,
        dpi: int = 150,
    ) -> "FlattenSettings":
        return cls(
            output_root=config.OUTPUT_DIR / config.PDF_FLATTEN_DIRNAME,
            max_pdf_bytes=config.MAX_PDF_SIZE_MB * MIB,
            timeout_seconds=config.PDF_FLATTEN_TIMEOUT,
            max_pages=config.PDF_FLATTEN_MAX_PAGES,
            job_ttl_seconds=config.PDF_FLATTEN_JOB_TTL_SECONDS,
            allow_signed=config.PDF_FLATTEN_ALLOW_SIGNED,
            flatten_forms=flatten_forms,
            flatten_annotations=flatten_annotations,
            flatten_stamps=flatten_stamps,
            full_flatten=full_flatten,
            dpi=max(72, min(300, dpi)),
        )


@dataclass(frozen=True)
class FlattenJob:
    root: Path

    @property
    def job_id(self) -> str:
        return self.root.name

    @property
    def input_path(self) -> Path:
        return self.root / INPUT_FILENAME

    @property
    def output_path(self) -> Path:
        return self.root / OUTPUT_FILENAME


@dataclass(frozen=True)
class FlattenResult:
    output_path: Path
    page_count: int
    form_fields: int           # widgets found before flattening
    annotations: int           # general annotations found
    stamps: int                # stamp annotations found
    was_signed: bool           # True only when allow_signed let it through
    output_size_bytes: int


# --- logging helper -------------------------------------------------------------
def _log(level: int, event: str, **fields: object) -> None:
    """Structured key=value logging. Never pass document content or field values."""
    logger.log(level, "%s %s", event, " ".join(f"{k}={v}" for k, v in fields.items()))


# --- validation -------------------------------------------------------------------
def validate_upload_metadata(
    filename: str | None, content_type: str | None, size: int | None, settings: FlattenSettings
) -> None:
    """Cheap pre-checks. The filename is used ONLY for its extension, never for paths."""
    if Path(filename or "").suffix.lower() != ".pdf":
        raise UnsupportedMediaTypeError("Only files with a .pdf extension are accepted.")
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime and mime not in _ACCEPTED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError("The uploaded file is not declared as a PDF.")
    if size is not None and size > settings.max_pdf_bytes:
        raise FileTooLargeError(_too_large_message(settings))


def _too_large_message(settings: FlattenSettings) -> str:
    return f"The PDF exceeds the maximum allowed size of {settings.max_pdf_bytes / MIB:.0f} MB."


# --- job directory lifecycle -------------------------------------------------------
def create_job(settings: FlattenSettings) -> FlattenJob:
    purge_stale_jobs(settings)
    root = settings.output_root / uuid.uuid4().hex
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    return FlattenJob(root=root)


def cleanup_job(job_root: Path) -> None:
    """Remove a job directory. Refuses anything that isn't a UUID-named dir."""
    if not _JOB_ID_RE.match(job_root.name):
        _log(logging.ERROR, "pdf_flatten.cleanup_refused", reason="unexpected_name")
        return
    try:
        shutil.rmtree(job_root)
        _log(logging.INFO, "pdf_flatten.cleaned", job_id=job_root.name)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("pdf_flatten.cleanup_failed job_id=%s", job_root.name)


def purge_stale_jobs(settings: FlattenSettings) -> None:
    """Safety net for jobs orphaned by crashes or client disconnects."""
    try:
        entries = list(settings.output_root.iterdir())
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("pdf_flatten.purge_failed")
        return
    cutoff = time.time() - settings.job_ttl_seconds
    for entry in entries:
        try:
            if _JOB_ID_RE.match(entry.name) and entry.is_dir() and entry.stat().st_mtime < cutoff:
                cleanup_job(entry)
        except OSError:
            logger.exception("pdf_flatten.purge_entry_failed")


# --- upload ----------------------------------------------------------------------
def save_upload(stream: BinaryIO, job: FlattenJob, settings: FlattenSettings) -> int:
    """Stream the upload to disk, enforcing signature and size limits."""
    total = 0
    checked_signature = False
    fd = os.open(job.input_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
    _log(logging.INFO, "pdf_flatten.validated", job_id=job.job_id, size_bytes=total)
    return total


# --- flattening ------------------------------------------------------------------
def flatten_pdf(job: FlattenJob, settings: FlattenSettings) -> FlattenResult:
    """Flatten ``job.input_path`` into ``job.output_path``."""
    started = time.monotonic()
    deadline = started + settings.timeout_seconds
    _log(logging.INFO, "pdf_flatten.started", job_id=job.job_id)
    try:
        with _open_pdf(job.input_path, settings) as doc:
            page_count = doc.page_count
            _log(logging.INFO, "pdf_flatten.opened", job_id=job.job_id, pages=page_count)

            signed = _has_signature(doc, deadline)
            if signed and not settings.allow_signed:
                raise PDFSignatureError(
                    "The PDF is digitally signed; flattening would invalidate the signature."
                )

            fields, annots, stamps = _count_interactive(doc, deadline)
            _log(logging.INFO, "pdf_flatten.detected", job_id=job.job_id,
                 form_fields=fields, annotations=annots, stamps=stamps, signed=signed)

            _refresh_widget_appearances(doc, deadline)
            _bake(doc, settings)
            _check_deadline(deadline)
            _strip_active_content(doc, settings, deadline)

            if settings.full_flatten:
                # Render each page to an image and embed into a clean non-selectable PDF
                flat_doc = _rasterize_to_flat_pdf(doc, settings, deadline)
                try:
                    _save(flat_doc, job.output_path)
                finally:
                    flat_doc.close()
            else:
                _save(doc, job.output_path)
        _verify_output(job.output_path, page_count, settings)
    except PDFFlattenError:
        _log(logging.WARNING, "pdf_flatten.failed", job_id=job.job_id)
        raise
    except Exception as exc:
        logger.error("pdf_flatten.failed job_id=%s error_type=%s", job.job_id,
                     type(exc).__name__, exc_info=True)
        raise PDFFlattenError("Unable to flatten the uploaded PDF.") from exc
    finally:
        job.input_path.unlink(missing_ok=True)   # the upload is no longer needed

    size = job.output_path.stat().st_size
    _log(logging.INFO, "pdf_flatten.completed", job_id=job.job_id, form_fields=fields,
         annotations=annots, stamps=stamps, output_bytes=size, seconds=f"{time.monotonic() - started:.2f}")
    return FlattenResult(
        output_path=job.output_path,
        page_count=page_count,
        form_fields=fields,
        annotations=annots,
        stamps=stamps,
        was_signed=signed,
        output_size_bytes=size,
    )


def _open_pdf(path: Path, settings: FlattenSettings) -> pymupdf.Document:
    try:
        doc = pymupdf.open(str(path), filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several types for damaged input
        logger.warning("pdf_flatten.open_failed error_type=%s", type(exc).__name__)
        raise PDFOpenError("The uploaded file is not a readable PDF (it may be corrupted).") from exc
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise PDFEncryptedError("Encrypted or password-protected PDFs are not supported.")
        if not doc.is_pdf or doc.page_count == 0:
            raise PDFOpenError("The uploaded file is not a readable PDF (it may be corrupted).")
        if doc.page_count > settings.max_pages:
            raise ResourceLimitError(f"The PDF has more than {settings.max_pages} pages.")
        if doc.is_repaired:
            logger.warning("pdf_flatten.pdf_was_repaired")
    except Exception:
        doc.close()
        raise
    return doc


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise PDFTimeoutError("Flattening exceeded the allowed processing time.")


def _has_signature(doc: pymupdf.Document, deadline: float) -> bool:
    """True if the document contains a *signed* signature field.

    Empty (unsigned) signature fields don't count. We only detect signatures;
    their cryptographic validity is not checked.
    """
    flags = doc.get_sigflags()   # -1: no form, 0: no signatures, >0: bit flags
    if flags is not None and flags > 0 and flags & SIGFLAGS_SIGNATURES_EXIST:
        return True
    for page in doc:
        _check_deadline(deadline)
        for widget in page.widgets([pymupdf.PDF_WIDGET_TYPE_SIGNATURE]):
            if doc.xref_get_key(widget.xref, "V")[0] != "null":
                return True
    return False


def _count_interactive(doc: pymupdf.Document, deadline: float) -> tuple[int, int, int]:
    """Returns (form_fields_count, general_annots_count, stamps_count)."""
    fields = annots = stamps = 0
    for page in doc:
        _check_deadline(deadline)
        fields += sum(1 for _ in page.widgets())
        for a in page.annots():
            atype = a.type[0]
            if atype == pymupdf.PDF_ANNOT_STAMP:
                stamps += 1
            elif atype not in _UNCOUNTED_ANNOT_TYPES:
                annots += 1
    return fields, annots, stamps


def _refresh_widget_appearances(doc: pymupdf.Document, deadline: float) -> None:
    """Regenerate appearance streams when the PDF says viewers must (NeedAppearances).

    MuPDF can only bake an existing appearance, so fields without one would
    otherwise flatten to nothing.
    """
    if not doc.need_appearances():
        return
    for page in doc:
        _check_deadline(deadline)
        for widget in page.widgets():
            if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                continue
            try:
                widget.update()
            except Exception as exc:  # keep going: the stored appearance may still be usable
                logger.debug("pdf_flatten.widget_refresh_failed error_type=%s", type(exc).__name__)
    doc.need_appearances(False)


def _bake(doc: pymupdf.Document, settings: FlattenSettings) -> None:
    """Merge widgets, general annotations, and/or stamps into page content."""
    # Case 1: Both general annotations and stamps should be flattened (or kept) together
    if settings.flatten_annotations == settings.flatten_stamps:
        doc.bake(annots=settings.flatten_annotations, widgets=settings.flatten_forms)
        return

    # Case 2: Granular annotation baking
    # Either bake general annotations while keeping stamps, or bake stamps while keeping general annotations.
    for page in doc:
        annots_to_bake = []
        annots_to_keep = []
        for a in page.annots():
            if a.type[0] in _UNCOUNTED_ANNOT_TYPES:
                continue
            is_stamp = (a.type[0] == pymupdf.PDF_ANNOT_STAMP)
            should_bake = settings.flatten_stamps if is_stamp else settings.flatten_annotations
            if should_bake:
                annots_to_bake.append(a)
            else:
                annots_to_keep.append(a)

        if settings.flatten_stamps and not settings.flatten_annotations:
            # Bake stamps individually by rendering their appearance into page images
            for stamp in annots_to_bake:
                try:
                    rect = stamp.rect
                    pix = stamp.get_pixmap(dpi=150)
                    page.delete_annot(stamp)
                    page.insert_image(rect, pixmap=pix)
                except Exception as exc:
                    logger.debug("Failed baking stamp individually: %s", exc)

        elif settings.flatten_annotations and not settings.flatten_stamps:
            # Flatten general annotations but temporarily hide stamps from /Annots array
            kept_xrefs = [f"{a.xref} 0 R" for a in annots_to_keep]
            baked_xrefs = [f"{a.xref} 0 R" for a in annots_to_bake]
            all_xrefs = kept_xrefs + baked_xrefs
            if baked_xrefs:
                # Set /Annots array to only contain the items we want baked
                doc.xref_set_key(page.xref, "Annots", f"[{' '.join(baked_xrefs)}]")
                doc.bake(annots=True, widgets=False)
                # Re-attach kept annotations (e.g. stamps)
                doc.xref_set_key(page.xref, "Annots", f"[{' '.join(kept_xrefs)}]")

    # Finally bake form fields if requested
    if settings.flatten_forms:
        doc.bake(annots=False, widgets=True)


def _strip_active_content(doc: pymupdf.Document, settings: FlattenSettings, deadline: float) -> None:
    """Remove JavaScript, auto-actions and the AcroForm (when forms are flattened)."""
    for page in doc:
        _check_deadline(deadline)
        doc.xref_set_key(page.xref, "AA", "null")
        for link in page.get_links():
            xref = link.get("xref", 0)
            if xref and doc.xref_get_key(xref, "A/S")[1] in _ACTIVE_ACTIONS:
                page.delete_link(link)
    doc.scrub(
        attached_files=False, clean_pages=False, embedded_files=False, hidden_text=False,
        javascript=True, metadata=False, redactions=False, redact_images=0,
        remove_links=False, reset_fields=False,
        reset_responses=False, thumbnails=False, xml_metadata=False,
    )
    if settings.flatten_forms:
        catalog = doc.pdf_catalog()
        for key in _CATALOG_KEYS_TO_REMOVE:
            doc.xref_set_key(catalog, key, "null")


def _rasterize_to_flat_pdf(
    doc: pymupdf.Document, settings: FlattenSettings, deadline: float
) -> pymupdf.Document:
    """
    Render every page to a high-resolution raster image and reconstruct a new PDF.
    This produces a completely flattened PDF where text is 100% non-selectable and non-editable.
    Page dimensions and orientations are preserved exactly.
    """
    flat_doc = pymupdf.open()
    try:
        for page_idx in range(doc.page_count):
            _check_deadline(deadline)
            orig_page = doc[page_idx]
            pix = orig_page.get_pixmap(dpi=settings.dpi, alpha=False)
            new_page = flat_doc.new_page(
                width=orig_page.rect.width,
                height=orig_page.rect.height,
            )
            new_page.insert_image(new_page.rect, pixmap=pix)
        return flat_doc
    except Exception:
        flat_doc.close()
        raise


def _save(doc: pymupdf.Document, output_path: Path) -> None:
    doc.save(str(output_path), garbage=3, deflate=True)


def _verify_output(path: Path, expected_pages: int, settings: FlattenSettings) -> None:
    """Reopen the result and confirm it is valid and non-interactive where expected."""
    try:
        with pymupdf.open(str(path), filetype="pdf") as out:
            if out.needs_pass or not out.is_pdf or out.page_count != expected_pages:
                raise PDFFlattenError("Unable to flatten the uploaded PDF.")
            if settings.flatten_forms:
                if any(page.first_widget for page in out):
                    raise PDFFlattenError("Unable to flatten the uploaded PDF.")
                if out.xref_get_key(out.pdf_catalog(), "AcroForm")[0] != "null":
                    raise PDFFlattenError("Unable to flatten the uploaded PDF.")
    except PDFFlattenError:
        raise
    except Exception as exc:
        raise PDFFlattenError("Unable to flatten the uploaded PDF.") from exc
    _log(logging.INFO, "pdf_flatten.output_validated", pages=expected_pages)