"""Shared PDF processing utilities."""
from .validator import validate_pdf, PDFValidationError, UnsupportedPDFError

__all__ = [
    "validate_pdf",
    "PDFValidationError",
    "UnsupportedPDFError",
]
