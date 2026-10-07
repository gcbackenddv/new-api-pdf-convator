"""Visual page comparison – works with or without OpenCV."""
from __future__ import annotations

import logging
from typing import List

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


def visual_similarity(img_a: Image.Image, img_b: Image.Image) -> float:
    size = (400, 400)
    a = np.array(img_a.convert("L").resize(size, Image.Resampling.BILINEAR), dtype=float)
    b = np.array(img_b.convert("L").resize(size, Image.Resampling.BILINEAR), dtype=float)
    mse = np.mean((a - b) ** 2)
    return float(1.0 / (1.0 + mse / 1000.0))


def find_visual_changes(
    img_old: Image.Image,
    img_new: Image.Image,
    *,
    page_old: int,
    page_new: int,
) -> List[Difference]:
    settings = get_settings()
    threshold = settings.pdf_compare_visual_threshold
    min_area = settings.pdf_compare_min_change_area

    size = (800, 800)
    a = np.array(img_old.convert("L").resize(size, Image.Resampling.BILINEAR))
    b = np.array(img_new.convert("L").resize(size, Image.Resampling.BILINEAR))
    diff = np.abs(a.astype(int) - b.astype(int)).astype(np.uint8)
    mask = (diff > int(255 * threshold)).astype(np.uint8) * 255

    diffs: List[Difference] = []
    if _HAS_CV2:
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            scale_x = img_old.width / size[0]
            scale_y = img_old.height / size[1]
            bbox = [x * scale_x, y * scale_y, (x + w) * scale_x, (y + h) * scale_y]
            diffs.append(
                Difference(
                    change_type=ChangeType.VISUAL,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Visual change region ({int(area)} px)",
                    bbox_old=bbox,
                    bbox_new=bbox,
                    severity="medium" if area < 5000 else "high",
                )
            )
    else:
        # Fallback: single whole-page change if similarity is low
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
    return diffs
