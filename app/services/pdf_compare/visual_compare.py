"""Visual page comparison – SSIM and contour detection with side-by-side diff overlay."""
from __future__ import annotations

import base64
import io
import logging
from typing import List, Tuple

import numpy as np
from PIL import Image

from app.config import get_settings
from .models import ChangeType, Difference

logger = logging.getLogger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    logger.warning("OpenCV not available – visual contour detection limited")


def compute_ssim(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """Compute Structural Similarity Index (SSIM) between two grayscale uint8 images."""
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


def visual_similarity(img_a: Image.Image, img_b: Image.Image) -> float:
    """Accurate visual similarity using SSIM over normalized resolution."""
    size = (600, 600)
    a = np.array(img_a.convert("L").resize(size, Image.Resampling.BILINEAR), dtype=np.uint8)
    b = np.array(img_b.convert("L").resize(size, Image.Resampling.BILINEAR), dtype=np.uint8)
    return compute_ssim(a, b)


def find_visual_changes(
    img_old: Image.Image,
    img_new: Image.Image,
    *,
    page_old: int,
    page_new: int,
) -> Tuple[List[Difference], Image.Image | None]:
    """
    Find visual difference regions between two page images.
    Returns list of Differences and an annotated side-by-side diff PIL Image.
    """
    settings = get_settings()
    threshold = getattr(settings, "PDF_COMPARE_VISUAL_THRESHOLD", 0.12)
    min_area = getattr(settings, "PDF_COMPARE_MIN_CHANGE_AREA", 500)

    # Use native or high-res for accurate bounding boxes
    w = max(img_old.width, img_new.width)
    h = max(img_old.height, img_new.height)
    # Standardize to common canvas size up to 1000px max
    max_dim = 1000
    scale = min(1.0, max_dim / max(w, h))
    target_w = max(int(w * scale), 100)
    target_h = max(int(h * scale), 100)

    a_pil = img_old.convert("RGB").resize((target_w, target_h), Image.Resampling.BILINEAR)
    b_pil = img_new.convert("RGB").resize((target_w, target_h), Image.Resampling.BILINEAR)

    a_gray = np.array(a_pil.convert("L"), dtype=np.uint8)
    b_gray = np.array(b_pil.convert("L"), dtype=np.uint8)

    diff = np.abs(a_gray.astype(int) - b_gray.astype(int)).astype(np.uint8)
    thresh_val = max(int(255 * threshold), 20)
    mask = (diff > thresh_val).astype(np.uint8) * 255

    diffs: List[Difference] = []
    diff_image: Image.Image | None = None

    if _HAS_CV2:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        mask_clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask_clean = cv2.morphologyEx(mask_clean, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        a_cv = cv2.cvtColor(np.array(a_pil), cv2.COLOR_RGB2BGR)
        b_cv = cv2.cvtColor(np.array(b_pil), cv2.COLOR_RGB2BGR)

        detected_boxes = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            # scale min_area relative to resized canvas
            scaled_min_area = min_area * (scale ** 2)
            if area < scaled_min_area:
                continue

            x, y, bw, bh = cv2.boundingRect(cnt)
            detected_boxes.append((x, y, bw, bh, area))

            # Scale coordinates back to original old/new image size
            scale_x_old = img_old.width / target_w
            scale_y_old = img_old.height / target_h
            scale_x_new = img_new.width / target_w
            scale_y_new = img_new.height / target_h

            bbox_o = [x * scale_x_old, y * scale_y_old, (x + bw) * scale_x_old, (y + bh) * scale_y_old]
            bbox_n = [x * scale_x_new, y * scale_y_new, (x + bw) * scale_x_new, (y + bh) * scale_y_new]

            diffs.append(
                Difference(
                    change_type=ChangeType.VISUAL,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Visual difference in page region ({int(area / (scale**2))} px)",
                    bbox_old=bbox_o,
                    bbox_new=bbox_n,
                    severity="high" if area > scaled_min_area * 5 else "medium",
                )
            )

            # Draw visual highlight boxes: Red for old, Green for new
            cv2.rectangle(a_cv, (x, y), (x + bw, y + bh), (0, 0, 230), 2)
            cv2.rectangle(b_cv, (x, y), (x + bw, y + bh), (0, 180, 0), 2)

        if detected_boxes:
            # Add headers to the comparison image
            header_h = 36
            header_bar = np.ones((header_h, target_w * 2 + 10, 3), dtype=np.uint8) * 245
            cv2.putText(header_bar, f"Page {page_old} (Original - Removed)", (15, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 180), 2)
            cv2.putText(header_bar, f"Page {page_new} (Revised - Added)", (target_w + 25, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 130, 0), 2)

            divider = np.ones((target_h, 10, 3), dtype=np.uint8) * 220
            combined_body = np.hstack([a_cv, divider, b_cv])
            combined = np.vstack([header_bar, combined_body])
            diff_image = Image.fromarray(cv2.cvtColor(combined, cv2.COLOR_BGR2RGB))
    else:
        changed_ratio = float(np.mean(mask > 0))
        if changed_ratio > threshold:
            diffs.append(
                Difference(
                    change_type=ChangeType.VISUAL,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Visual difference detected ({changed_ratio:.1%} pixels)",
                    severity="medium",
                )
            )
            # Simple side-by-side
            side = Image.new("RGB", (target_w * 2, target_h))
            side.paste(a_pil, (0, 0))
            side.paste(b_pil, (target_w, 0))
            diff_image = side

    return diffs, diff_image


def image_to_base64_data_uri(img: Image.Image, max_width: int = 700) -> str:
    """Downscale and compress diff image to a lightweight JPEG data URI for HTML reports."""
    w, h = img.size
    if w > max_width:
        new_h = int(h * (max_width / w))
        img = img.resize((max_width, new_h), Image.Resampling.BILINEAR)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
