from app.services.pdf_to_pptx.coordinates import calculate_optimal_dpi
from app.services.pdf_to_pptx.converter import (
    PdfToPptxError,
    PdfToPptxResult,
    convert_pdf_to_pptx,
)

__all__ = ["PdfToPptxError", "PdfToPptxResult", "calculate_optimal_dpi", "convert_pdf_to_pptx"]
