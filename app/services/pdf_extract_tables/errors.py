"""Application exceptions. Messages are client-safe: never include paths or library text."""
from __future__ import annotations


class TableExtractionError(Exception):
    """Base class; also used for generic failures."""


class PDFValidationError(TableExtractionError):
    """The upload itself is invalid (e.g. empty)."""


class UnsupportedMediaTypeError(PDFValidationError):
    """Extension / MIME type / signature say this is not a PDF."""


class FileTooLargeError(PDFValidationError):
    """Upload exceeds the configured maximum size."""


class InvalidOptionsError(PDFValidationError):
    """Request options are inconsistent or out of range."""


class UnsupportedPDFError(TableExtractionError):
    """Valid PDF we refuse to process (e.g. password protected)."""


class PDFExtractionError(TableExtractionError):
    """The PDF could not be opened or read (corrupted, malformed)."""


class NoTablesFoundError(TableExtractionError):
    """No (matching) tables were detected."""


class OCRProcessingError(TableExtractionError):
    """OCR failed on a page."""


class OCRUnavailableError(OCRProcessingError):
    """OCR is required but disabled or not installed."""


class ResourceLimitError(TableExtractionError):
    """A configured resource limit was exceeded."""


class ExtractionTimeoutError(ResourceLimitError):
    """A cooperative deadline expired."""


class TableTooLargeError(TableExtractionError):
    """Internal: one table exceeds the row/column limits (engine skips it with a warning)."""


class ExportError(TableExtractionError):
    """Exporting the normalized model failed."""