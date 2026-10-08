"""Service for repairing corrupted or damaged PDF documents."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pymupdf as fitz

from app.config import get_settings
from app.services.pdf_repair import repair_pdf as _enhanced_repair, PDFRepairError
from .validator import PDFValidationError

logger = logging.getLogger(__name__)


def repair_pdf(src: Path, dst: Path) -> dict[str, Any]:
    """Repair damaged or malformed PDF using the enhanced multi-strategy repair engine.

    Backward-compatible wrapper for app.services.pdf_repair.
    """
    try:
        res = _enhanced_repair(src, dst)
        return {
            "page_count": res.page_count,
            "was_repaired": res.was_repaired,
        }
    except PDFRepairError as exc:
        raise PDFValidationError(exc.message) from exc

