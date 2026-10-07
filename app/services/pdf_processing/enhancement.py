"""Conservative image enhancement – OpenCV optional."""
from __future__ import annotations

import logging

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


def enhance_image(
    img: Image.Image,
    *,
    grayscale: bool = False,
    contrast: float = 1.0,
    brightness: float = 1.0,
    sharpen: float = 0.0,
    denoise: bool = False,
    threshold: bool = False,
    background_cleanup: bool = False,
) -> Image.Image:
    out = img.copy()

    if grayscale and out.mode != "L":
        out = out.convert("L")

    if brightness != 1.0:
        out = ImageEnhance.Brightness(out).enhance(brightness)

    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)

    if denoise and _HAS_CV2:
        arr = np.array(out)
        if len(arr.shape) == 2:
            arr = cv2.fastNlMeansDenoising(arr, None, 8, 7, 21)
        else:
            arr = cv2.fastNlMeansDenoisingColored(arr, None, 8, 8, 7, 21)
        out = Image.fromarray(arr)

    if sharpen > 0:
        out = out.filter(ImageFilter.UnsharpMask(radius=1, percent=int(sharpen * 100), threshold=2))

    if background_cleanup and out.mode == "L":
        arr = np.array(out)
        arr = np.where(arr > 200, 255, arr).astype(np.uint8)
        out = Image.fromarray(arr)

    if threshold:
        out = out.convert("L")
        arr = np.array(out)
        if _HAS_CV2:
            _, arr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            arr = np.where(arr > 128, 255, 0).astype(np.uint8)
        out = Image.fromarray(arr)

    return out
