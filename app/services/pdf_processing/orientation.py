"""Detect page orientation (0/90/180/270) via OSD or heuristics."""
from __future__ import annotations

import logging
from typing import Tuple

from PIL import Image

logger = logging.getLogger(__name__)

_OSD_AVAILABLE = False
try:
    import pytesseract
    _OSD_AVAILABLE = True
except ImportError:
    pass


def detect_orientation(img: Image.Image) -> Tuple[int, float]:
    """
    Detect rotation needed to make text upright.
    Returns (degrees_clockwise_to_correct, confidence 0-1).
    Possible values: 0, 90, 180, 270.
    """
    if not _OSD_AVAILABLE:
        return 0, 0.0

    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        rotate = int(osd.get("rotate", 0))
        conf = float(osd.get("orientation_conf", 0)) / 100.0
        # tesseract 'rotate' is the amount to rotate CCW to correct
        # we return clockwise correction for consistency with deskew
        cw = (360 - rotate) % 360
        if cw not in (0, 90, 180, 270):
            return 0, 0.0
        return cw, max(0.0, min(1.0, conf))
    except Exception as exc:
        logger.debug("OSD failed: %s", exc)
        return 0, 0.0
