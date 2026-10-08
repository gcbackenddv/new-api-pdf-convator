from app.services.pdf_to_pptx.coordinates import calculate_optimal_dpi
from app.services.pdf_to_pptx.converter import (
    PdfToPptxError,
    PdfToPptxResult,
    convert_pdf_to_pptx,
)
from app.services.pdf_to_pptx.font_embedder import embed_fonts_from_pdf
from app.services.pdf_to_pptx.fonts import normalize_font_name, resolve_font_styling
from app.services.pdf_to_pptx.validator import (
    PageValidationDetail,
    PptxValidationReport,
    validate_and_score_pptx,
)

__all__ = [
    "PdfToPptxError",
    "PdfToPptxResult",
    "PageValidationDetail",
    "PptxValidationReport",
    "calculate_optimal_dpi",
    "convert_pdf_to_pptx",
    "embed_fonts_from_pdf",
    "normalize_font_name",
    "resolve_font_styling",
    "validate_and_score_pptx",
]
