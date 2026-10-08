"""Production-ready PDF Repair service.

Performs multi-engine repair, structure analysis, clean rewriting, and post-repair validation.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import pymupdf as fitz

from app.config import get_settings

logger = logging.getLogger(__name__)


class PDFRepairError(Exception):
    """Client-facing repair failure with HTTP status code mapping."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class PDFRepairResult:
    """Detailed result of a PDF repair execution."""
    success: bool
    page_count: int
    was_repaired: bool
    repair_method: str  # "mupdf_clean", "mupdf_rebuild", "ghostscript", "noop"
    issues_detected: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    output_size_bytes: int = 0


def _detect_pre_repair_issues(src: Path) -> tuple[List[str], bool, bool]:
    """Inspect raw bytes and PDF structures to detect specific corruption issues."""
    issues: List[str] = []
    has_pdf_header = False
    is_encrypted = False

    size = src.stat().st_size
    with open(src, "rb") as f:
        # Read first 1024 bytes looking for PDF magic signature
        header_sample = f.read(1024)
        if b"%PDF-" in header_sample:
            has_pdf_header = True
            if not header_sample.startswith(b"%PDF-"):
                issues.append("PDF header has preceding garbage bytes")
        else:
            issues.append("Missing %PDF- header signature")

        # Read last 2048 bytes looking for EOF and startxref
        if size > 100:
            seek_pos = max(0, size - 2048)
            f.seek(seek_pos)
            tail_sample = f.read()
            if b"%%EOF" not in tail_sample:
                issues.append("Missing %%EOF trailer marker (truncated file)")
            if b"startxref" not in tail_sample:
                issues.append("Missing or damaged startxref offset pointer")

    return issues, has_pdf_header, is_encrypted


def _attempt_mupdf_repair(src: Path, dst: Path) -> Optional[tuple[int, bool, str]]:
    """Attempt repair and reconstruction using PyMuPDF (MuPDF C engine)."""
    try:
        doc = fitz.open(src)
    except Exception as exc:
        logger.debug("MuPDF initial open failed: %s", exc)
        return None

    try:
        if doc.is_encrypted or doc.needs_pass:
            raise PDFRepairError("Encrypted or password-protected PDFs cannot be repaired without credentials.", 400)

        page_count = doc.page_count
        if page_count == 0:
            return None

        was_repaired = bool(doc.is_repaired)
        method = "mupdf_rebuild" if was_repaired else "mupdf_clean"

        dst.parent.mkdir(parents=True, exist_ok=True)
        # garbage=4: compact streams, remove unused objects, deduplicate fonts/images
        # clean=True: sanitize syntax and re-index page tree
        # deflate=True: deflate streams for standard compression
        doc.save(
            dst,
            garbage=4,
            deflate=True,
            clean=True,
            linear=False,
            pretty=False,
        )
        return page_count, was_repaired, method
    except PDFRepairError:
        raise
    except Exception as exc:
        logger.debug("MuPDF save failed: %s", exc)
        return None
    finally:
        doc.close()


def _attempt_ghostscript_repair(src: Path, dst: Path) -> Optional[tuple[int, bool, str]]:
    """Attempt deep structure repair using Ghostscript pdfwrite if MuPDF fails."""
    gs_bin = shutil.which("gs")
    if not gs_bin:
        return None

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        gs_bin,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        "-dPDFSETTINGS=/default",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dPrinted=false",
        f"-sOutputFile={dst}",
        str(src),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            logger.debug("Ghostscript repair failed with returncode=%d: %s", res.returncode, res.stderr)
            return None

        # Verify GS output
        doc = fitz.open(dst)
        count = doc.page_count
        doc.close()
        if count == 0:
            return None

        return count, True, "ghostscript"
    except subprocess.TimeoutExpired:
        logger.warning("Ghostscript repair timed out after 30s")
        return None
    except Exception as exc:
        logger.debug("Ghostscript execution failed: %s", exc)
        return None


def _validate_repaired_pdf(dst: Path, max_pages: int) -> int:
    """Thorough post-repair validation ensuring the repaired PDF is healthy and readable."""
    if not dst.exists() or not dst.is_file():
        raise PDFRepairError("Repaired PDF output file was not created.", 500)

    if dst.stat().st_size == 0:
        raise PDFRepairError("Repaired PDF output is empty.", 500)

    try:
        doc = fitz.open(dst)
    except Exception as exc:
        logger.error("Repaired PDF failed validation check: %s", exc)
        raise PDFRepairError("The repaired output is not a valid PDF document.", 500) from exc

    try:
        if doc.is_encrypted:
            raise PDFRepairError("The repaired PDF unexpectedly has encryption applied.", 500)

        page_count = doc.page_count
        if page_count == 0:
            raise PDFRepairError("The repaired PDF contains no readable pages.", 500)

        if page_count > max_pages:
            raise PDFRepairError(f"PDF exceeds the maximum supported page limit of {max_pages}.", 413)

        # Verify page accessibility on first, middle, and last page
        check_indices = {0, page_count // 2, page_count - 1}
        for idx in check_indices:
            page = doc.load_page(idx)
            # Ensure geometry and rect can be evaluated
            _ = page.rect
            del page

        return page_count
    except PDFRepairError:
        raise
    except Exception as exc:
        logger.error("Page accessibility validation failed: %s", exc)
        raise PDFRepairError("The repaired PDF pages could not be safely read.", 500) from exc
    finally:
        doc.close()


def repair_pdf(src: Path, dst: Path) -> PDFRepairResult:
    """Main entry point to repair a damaged or corrupted PDF.

    1. Validates upload prerequisites and checks file signatures.
    2. Analyzes corruption signs (broken xref, missing trailer/eof, malformed header).
    3. Executes multi-tier recovery (MuPDF repair -> Ghostscript fallback).
    4. Validates the resulting PDF strictly.
    5. Returns repair metadata.
    """
    settings = get_settings()
    started = time.perf_counter()

    logger.info("🔧 [PDF-Repair] Repair started for: %s (size=%d bytes)", src.name, src.stat().st_size if src.exists() else 0)

    # 1. Basic filesystem & size validation
    if not src.exists() or not src.is_file():
        raise PDFRepairError("The file does not exist.", 400)

    size = src.stat().st_size
    if size == 0:
        raise PDFRepairError("The uploaded file is empty.", 400)

    if size > settings.max_pdf_size_bytes:
        raise PDFRepairError(
            f"PDF exceeds maximum allowed size of {settings.MAX_PDF_SIZE_MB} MB.", 413
        )

    # 2. Pre-repair inspection
    detected_issues, has_pdf_header, is_encrypted = _detect_pre_repair_issues(src)
    with open(src, "rb") as f:
        sample_chunk = f.read(65536)

    if not has_pdf_header:
        if b"%PDF-" not in sample_chunk and b"obj" not in sample_chunk:
            raise PDFRepairError("The uploaded file is not a PDF document (invalid file header).", 400)

    # If the file has a %PDF header but zero object structures, trailer, or catalog, it contains no recoverable data
    has_recoverable_tokens = (
        b"obj" in sample_chunk
        or b"xref" in sample_chunk
        or b"/Page" in sample_chunk
        or b"stream" in sample_chunk
        or b"trailer" in sample_chunk
    )
    if not has_recoverable_tokens:
        logger.warning("❌ [PDF-Repair] File %s contains no PDF objects or stream markers", src.name)
        raise PDFRepairError("The PDF contains irrecoverably destroyed data and could not be repaired.", 400)

    if detected_issues:
        logger.info("🔧 [PDF-Repair] Detected potential issues: %s", ", ".join(detected_issues))

    # 3. Attempt Repair Pipeline
    repair_info = None

    # Tier 1: MuPDF reconstruction & sanitization
    try:
        repair_info = _attempt_mupdf_repair(src, dst)
    except PDFRepairError:
        raise
    except Exception as exc:
        logger.debug("MuPDF repair attempt failed: %s", exc)

    # Tier 2: Ghostscript rebuild fallback
    if repair_info is None:
        logger.info("🔧 [PDF-Repair] MuPDF repair inconclusive; falling back to Ghostscript engine...")
        try:
            repair_info = _attempt_ghostscript_repair(src, dst)
        except Exception as exc:
            logger.debug("Ghostscript repair attempt failed: %s", exc)

    if repair_info is None:
        logger.warning("❌ [PDF-Repair] All repair strategies failed for %s", src.name)
        raise PDFRepairError("The PDF contains irrecoverably destroyed data and could not be repaired.", 400)

    page_count, was_repaired, method = repair_info

    # 4. Post-repair validation
    validated_pages = _validate_repaired_pdf(dst, settings.MAX_PDF_PAGES)

    elapsed_ms = (time.perf_counter() - started) * 1000
    out_size = dst.stat().st_size

    logger.info(
        "✅ [PDF-Repair] Successfully repaired! pages=%d, method=%s, size=%d bytes, elapsed=%.1fms",
        validated_pages, method, out_size, elapsed_ms,
    )

    return PDFRepairResult(
        success=True,
        page_count=validated_pages,
        was_repaired=was_repaired or (method != "mupdf_clean"),
        repair_method=method,
        issues_detected=detected_issues,
        processing_time_ms=elapsed_ms,
        output_size_bytes=out_size,
    )
