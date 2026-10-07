"""Page deskew – OpenCV when available, otherwise no-op."""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    logger.warning("OpenCV not available – deskew disabled")


def detect_skew(img: Image.Image, *, max_angle: float = 15.0) -> Tuple[float, float]:
    """Detect skew angle. Returns (angle_degrees, confidence 0-1)."""
    if not _HAS_CV2:
        return 0.0, 0.0

    arr = np.array(img.convert("L"))
    _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    edges = cv2.Canny(binary, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=80,
        minLineLength=min(arr.shape) // 4, maxLineGap=20,
    )
    if lines is None or len(lines) < 3:
        return 0.0, 0.0

    segments = np.asarray(lines).reshape(-1, 4)
    angles = []
    for x1, y1, x2, y2 in segments:
        if x2 == x1:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if angle < -45:
            angle += 90
        elif angle > 45:
            angle -= 90
        if abs(angle) <= max_angle:
            angles.append(angle)

    if not angles:
        return 0.0, 0.0

    median = float(np.median(angles))
    std = float(np.std(angles))
    confidence = max(0.0, min(1.0, 1.0 - std / 10.0))
    return median, confidence


def deskew_image(img: Image.Image, angle: float) -> Image.Image:
    if abs(angle) < 0.1:
        return img
    return img.rotate(-angle, expand=False, fillcolor="white" if img.mode == "RGB" else 255)
