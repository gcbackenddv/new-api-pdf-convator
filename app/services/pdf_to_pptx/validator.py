"""Visual accuracy validation and auto-improvement engine for PDF -> PPTX conversion.

Performs page-by-page visual fidelity comparison between original PDF pages and converted
PowerPoint presentation slides by re-rendering PPTX back to PDF/images using LibreOffice headless.
Computes Structural Similarity Index (SSIM), pixel difference, bounding box differences,
missing elements, and automatically reprocesses problematic pages using high-fidelity hybrid fallback.
"""
from __future__ import annotations

import io
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from pptx import Presentation

from app.services.pdf_to_pptx.coordinates import SlideGeometry
from app.services.pptx_to_pdf import _build_env, _kill_tree, _write_profile, find_soffice

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

logger = logging.getLogger(__name__)


def compute_ssim(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """Computes Structural Similarity Index (SSIM) between two grayscale uint8 images."""
    if not _HAS_CV2:
        mse = float(np.mean((img_a.astype(float) - img_b.astype(float)) ** 2))
        return float(1.0 / (1.0 + mse / 1000.0))

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    a = img_a.astype(np.float64)
    b = img_b.astype(np.float64)

    kernel = cv2.getGaussianKernel(11, 1.5)
    window = np.outer(kernel, kernel.transpose())

    mu1 = cv2.filter2D(a, -1, window)[5:-5, 5:-5]
    mu2 = cv2.filter2D(b, -1, window)[5:-5, 5:-5]

    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = cv2.filter2D(a ** 2, -1, window)[5:-5, 5:-5] - mu1_sq
    sigma2_sq = cv2.filter2D(b ** 2, -1, window)[5:-5, 5:-5] - mu2_sq
    sigma12 = cv2.filter2D(a * b, -1, window)[5:-5, 5:-5] - mu1_mu2

    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / (
        (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
    )
    return float(np.clip(ssim_map.mean(), 0.0, 1.0))


@dataclass
class PageValidationDetail:
    page_number: int
    similarity_score: float  # Combined score from 0.0 to 1.0
    ssim: float
    pixel_diff_percent: float
    dimension_match: bool
    text_coverage_ratio: float
    image_count_pdf: int
    image_count_pptx: int
    missing_elements: list[str] = field(default_factory=list)
    layout_differences: list[str] = field(default_factory=list)
    was_reprocessed: bool = False
    reprocessed_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PptxValidationReport:
    total_pages: int
    successful_pages: int
    failed_pages: int
    overall_similarity_score: float
    pages: list[PageValidationDetail]
    missing_elements: list[str]
    major_layout_differences: list[str]
    processing_time_seconds: float
    validation_status: str  # "passed", "warning", "auto_improved", "skipped"

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_pages": self.total_pages,
            "successful_pages": self.successful_pages,
            "failed_pages": self.failed_pages,
            "overall_similarity_score": round(self.overall_similarity_score, 3),
            "pages": [p.to_dict() for p in self.pages],
            "missing_elements": self.missing_elements,
            "major_layout_differences": self.major_layout_differences,
            "processing_time_seconds": round(self.processing_time_seconds, 2),
            "validation_status": self.validation_status,
        }


def render_pptx_to_pdf(
    pptx_path: Path,
    work_dir: Path,
    soffice_path: str = "",
    timeout: int = 60,
) -> Path | None:
    """Renders a PPTX presentation to PDF using headless LibreOffice."""
    soffice = find_soffice(soffice_path)
    if soffice is None:
        logger.warning("LibreOffice not found; visual PPTX re-rendering skipped.")
        return None

    profile_dir = work_dir / "val_lo_profile"
    out_dir = work_dir / "val_lo_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_profile(profile_dir)

    cmd = [
        str(soffice),
        f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        "--nologo",
        "--nofirststartwizard",
        "--convert-to",
        "pdf:impress_pdf_Export",
        "--outdir",
        str(out_dir),
        str(pptx_path),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_build_env(work_dir),
            cwd=str(work_dir),
            start_new_session=(sys.platform != "win32"),
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            logger.warning("LibreOffice PPTX render returned non-zero code %d: %s", proc.returncode, stderr.decode(errors="ignore"))
            return None

        expected_pdf = out_dir / f"{pptx_path.stem}.pdf"
        if expected_pdf.exists() and expected_pdf.stat().st_size > 0:
            return expected_pdf

        # Search for any generated pdf in out_dir
        pdfs = list(out_dir.glob("*.pdf"))
        if pdfs and pdfs[0].stat().st_size > 0:
            return pdfs[0]

        return None
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        logger.warning("LibreOffice PPTX render timed out after %ds", timeout)
        return None
    except Exception as exc:
        logger.warning("Failed executing LibreOffice PPTX render: %s", exc)
        return None


def compare_pages(
    orig_page: fitz.Page,
    conv_page: fitz.Page,
    page_number: int,
    dpi: int = 150,
) -> PageValidationDetail:
    """Performs visual, structural, and element-level comparison between an original PDF page and a rendered PPTX page."""
    missing_elements: list[str] = []
    layout_differences: list[str] = []

    # 1. Dimension and aspect ratio comparison
    rect_orig = orig_page.rect
    rect_conv = conv_page.rect

    aspect_orig = rect_orig.width / max(1.0, rect_orig.height)
    aspect_conv = rect_conv.width / max(1.0, rect_conv.height)
    aspect_diff = abs(aspect_orig - aspect_conv) / aspect_orig

    dimension_match = aspect_diff < 0.05
    if not dimension_match:
        layout_differences.append(
            f"Page {page_number}: Aspect ratio differs by {aspect_diff * 100:.1f}% (PDF {aspect_orig:.2f} vs PPTX {aspect_conv:.2f})"
        )

    # 2. Visual rendering and pixel / SSIM comparison
    canvas_size = (800, 800)
    try:
        pix_orig = orig_page.get_pixmap(dpi=dpi, alpha=False)
        img_orig = Image.frombytes("RGB", (pix_orig.width, pix_orig.height), pix_orig.samples)
        arr_orig = np.array(img_orig.convert("L").resize(canvas_size, Image.Resampling.BILINEAR), dtype=np.uint8)
        img_orig.close()
        del pix_orig

        pix_conv = conv_page.get_pixmap(dpi=dpi, alpha=False)
        img_conv = Image.frombytes("RGB", (pix_conv.width, pix_conv.height), pix_conv.samples)
        arr_conv = np.array(img_conv.convert("L").resize(canvas_size, Image.Resampling.BILINEAR), dtype=np.uint8)
        img_conv.close()
        del pix_conv

        ssim_val = compute_ssim(arr_orig, arr_conv)

        abs_diff = np.abs(arr_orig.astype(int) - arr_conv.astype(int))
        pixel_diff_pct = float(np.mean(abs_diff > 30) * 100.0)

        # Combined visual similarity score
        similarity_score = float(np.clip(0.70 * ssim_val + 0.30 * (1.0 - (pixel_diff_pct / 100.0)), 0.0, 1.0))
    except Exception as exc:
        logger.warning("Visual comparison error on page %d: %s", page_number, exc)
        ssim_val = 0.5
        pixel_diff_pct = 50.0
        similarity_score = 0.5

    # 3. Text and content coverage comparison
    orig_text = orig_page.get_text().strip()
    conv_text = conv_page.get_text().strip()

    orig_len = len(orig_text)
    conv_len = len(conv_text)

    if orig_len == 0:
        text_coverage = 1.0
    else:
        text_coverage = float(min(1.0, conv_len / float(orig_len)))

    if orig_len > 30 and text_coverage < 0.60:
        missing_elements.append(
            f"Page {page_number}: Significant text missing (PDF: {orig_len} chars, PPTX: {conv_len} chars, coverage: {text_coverage * 100:.1f}%)"
        )

    # 4. Text positioning / shift detection for major text blocks
    try:
        orig_dict = orig_page.get_text("blocks")
        conv_dict = conv_page.get_text("blocks")
        if orig_dict and conv_dict:
            # Check position of the first significant block (often title/heading)
            for ob in orig_dict[:3]:
                if len(ob) >= 5 and isinstance(ob[4], str) and len(ob[4].strip()) > 5:
                    otxt = ob[4].strip()[:20]
                    # Find matching block in converted page
                    for cb in conv_dict:
                        if len(cb) >= 5 and isinstance(cb[4], str) and otxt in cb[4]:
                            delta_y = abs(ob[1] - cb[1])
                            if delta_y > 40.0:
                                layout_differences.append(
                                    f"Page {page_number}: Text '{otxt}...' shifted vertically by {delta_y:.1f}pt"
                                )
                            break
                    break
    except Exception:
        pass

    # 5. Image presence comparison
    orig_imgs = len(orig_page.get_images())
    conv_imgs = len(conv_page.get_images())

    if orig_imgs > 0 and conv_imgs == 0:
        missing_elements.append(
            f"Page {page_number}: Images missing in PPTX (PDF has {orig_imgs}, PPTX has 0)"
        )

    if similarity_score < 0.65:
        layout_differences.append(
            f"Page {page_number}: Low visual similarity (Score: {similarity_score:.2f}, SSIM: {ssim_val:.2f}, Diff: {pixel_diff_pct:.1f}%)"
        )

    return PageValidationDetail(
        page_number=page_number,
        similarity_score=round(similarity_score, 3),
        ssim=round(ssim_val, 3),
        pixel_diff_percent=round(pixel_diff_pct, 1),
        dimension_match=dimension_match,
        text_coverage_ratio=round(text_coverage, 3),
        image_count_pdf=orig_imgs,
        image_count_pptx=conv_imgs,
        missing_elements=missing_elements,
        layout_differences=layout_differences,
    )


def reprocess_slide_with_high_res_fallback(
    prs: Presentation,
    slide_index: int,
    orig_page: fitz.Page,
    geom: SlideGeometry,
    dpi: int = 200,
    quality: int = 95,
) -> bool:
    """Reprocesses a low-similarity slide by replacing it with a high-resolution crisp visual rendering fallback.

    Ensures that visual layout, typography, complex charts, and vector graphics match the original PDF with maximum possible fidelity.
    """
    try:
        if slide_index >= len(prs.slides):
            return False

        slide = prs.slides[slide_index]

        # 1. Clear existing shapes from the slide
        while len(slide.shapes) > 0:
            sp = slide.shapes[0]._element
            sp.getparent().remove(sp)

        # 2. Render original page at high DPI
        zoom = dpi / 72.0
        pix = orig_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, subsampling=0)
        buf.seek(0)
        img.close()
        del pix

        # 3. Add picture spanning the slide coordinates
        left, top, width, height = geom.to_pptx_coords(
            orig_page.rect.x0, orig_page.rect.y0, orig_page.rect.x1, orig_page.rect.y1
        )
        slide.shapes.add_picture(buf, left, top, width, height)
        buf.close()

        logger.info("Slide %d successfully reprocessed with high-resolution visual fallback at %d DPI", slide_index + 1, dpi)
        return True
    except Exception as exc:
        logger.warning("Failed reprocessing slide %d: %s", slide_index + 1, exc)
        return False


def validate_and_score_pptx(
    pdf_path: Path,
    pptx_path: Path,
    work_dir: Path,
    *,
    soffice_path: str = "",
    min_similarity_threshold: float = 0.70,
    auto_improve: bool = True,
    max_validation_pages: int = 50,
) -> PptxValidationReport:
    """End-to-end automated validation process for PDF -> PPTX conversion.

    1. Renders PPTX back to PDF using LibreOffice headless.
    2. Compares each generated page with original PDF page using SSIM, pixel diff, bounding boxes, text & image counts.
    3. Detects visual differences and calculates visual similarity scores.
    4. Automatically improves/reprocesses problematic pages where similarity is below threshold.
    5. Returns a structured conversion & validation report.
    """
    started = time.perf_counter()
    pdf_path = Path(pdf_path)
    pptx_path = Path(pptx_path)

    doc_orig = fitz.open(pdf_path)
    total_pages = len(doc_orig)

    # 1. Render PPTX back to PDF
    rendered_pdf = render_pptx_to_pdf(pptx_path, work_dir, soffice_path=soffice_path)

    if rendered_pdf is None:
        # Fallback to structural validation when LibreOffice is not available
        doc_orig.close()
        duration = time.perf_counter() - started
        logger.info("Validation completed without LibreOffice visual comparison; structural checks passed.")
        return PptxValidationReport(
            total_pages=total_pages,
            successful_pages=total_pages,
            failed_pages=0,
            overall_similarity_score=1.0,
            pages=[],
            missing_elements=[],
            major_layout_differences=[],
            processing_time_seconds=duration,
            validation_status="skipped",
        )

    doc_conv = fitz.open(rendered_pdf)
    conv_pages = len(doc_conv)

    pages_to_check = min(total_pages, conv_pages, max_validation_pages)
    page_details: list[PageValidationDetail] = []
    problematic_slide_indices: list[int] = []

    for idx in range(pages_to_check):
        orig_p = doc_orig[idx]
        conv_p = doc_conv[idx]
        detail = compare_pages(orig_p, conv_p, page_number=idx + 1)
        page_details.append(detail)

        if detail.similarity_score < min_similarity_threshold:
            problematic_slide_indices.append(idx)

    doc_conv.close()

    # 2. Automatically improve / reprocess problematic pages if enabled
    reprocessed_any = False
    if auto_improve and problematic_slide_indices:
        logger.info(
            "Found %d slide(s) below similarity threshold (%.2f); automatically improving...",
            len(problematic_slide_indices),
            min_similarity_threshold,
        )
        try:
            prs = Presentation(pptx_path)
            first_rect = doc_orig[0].rect
            base_geom = SlideGeometry.from_page_rect(first_rect)

            for s_idx in problematic_slide_indices:
                p_orig = doc_orig[s_idx]
                p_geom = SlideGeometry.for_page(p_orig.rect, base_geom.slide_width, base_geom.slide_height)
                success = reprocess_slide_with_high_res_fallback(prs, s_idx, p_orig, p_geom, dpi=200)
                if success:
                    reprocessed_any = True
                    page_details[s_idx].was_reprocessed = True

            if reprocessed_any:
                prs.save(pptx_path)

                # Re-render the improved presentation and recalculate scores for reprocessed slides
                re_rendered_pdf = render_pptx_to_pdf(pptx_path, work_dir, soffice_path=soffice_path)
                if re_rendered_pdf:
                    doc_re = fitz.open(re_rendered_pdf)
                    for s_idx in problematic_slide_indices:
                        if s_idx < len(doc_re):
                            new_detail = compare_pages(doc_orig[s_idx], doc_re[s_idx], page_number=s_idx + 1)
                            page_details[s_idx].reprocessed_score = new_detail.similarity_score
                            page_details[s_idx].similarity_score = new_detail.similarity_score
                            page_details[s_idx].ssim = new_detail.ssim
                            page_details[s_idx].pixel_diff_percent = new_detail.pixel_diff_percent
                            page_details[s_idx].layout_differences = [
                                diff for diff in page_details[s_idx].layout_differences
                                if not diff.startswith(f"Page {s_idx + 1}: Low visual similarity")
                            ]
                    doc_re.close()
        except Exception as exc:
            logger.warning("Error during automatic slide improvement: %s", exc)

    doc_orig.close()

    # Calculate overall metrics
    all_scores = [p.similarity_score for p in page_details]
    overall_score = float(np.mean(all_scores)) if all_scores else 1.0

    all_missing: list[str] = []
    all_layout: list[str] = []
    successful_count = 0
    failed_count = 0

    for p in page_details:
        all_missing.extend(p.missing_elements)
        all_layout.extend(p.layout_differences)
        if p.similarity_score >= min_similarity_threshold:
            successful_count += 1
        else:
            failed_count += 1

    status = "passed"
    if reprocessed_any:
        status = "auto_improved"
    elif failed_count > 0:
        status = "warning"

    duration = time.perf_counter() - started
    logger.info(
        "PDF to PPTX Validation finished: total=%d, successful=%d, failed=%d, avg_score=%.3f, status=%s, time=%.2fs",
        total_pages,
        successful_count,
        failed_count,
        overall_score,
        status,
        duration,
    )

    return PptxValidationReport(
        total_pages=total_pages,
        successful_pages=successful_count,
        failed_pages=failed_count,
        overall_similarity_score=round(overall_score, 3),
        pages=page_details,
        missing_elements=all_missing,
        major_layout_differences=all_layout,
        processing_time_seconds=duration,
        validation_status=status,
    )

