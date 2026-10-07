"""
Application configuration.

All limits and paths are driven by environment variables so the same
codebase can run on a small Hostinger VPS or a larger server without
code changes.
"""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings:
    """Central configuration object. Instantiate once via get_settings()."""

    def __init__(self) -> None:
        # ------------------------------------------------------------------
        # Paths
        # ------------------------------------------------------------------
        project_root = Path(__file__).resolve().parent.parent
        self.OUTPUT_DIR: Path = Path(
            _env("OUTPUT_DIR", str(project_root / "converted_files"))
        )
        self.TEMP_DIR: Path = Path(
            _env("TEMP_DIR", "/tmp/pdf_platform")
        )

        # ------------------------------------------------------------------
        # Global limits
        # ------------------------------------------------------------------
        self.MAX_PDF_SIZE_MB: int = _env_int("MAX_PDF_SIZE_MB", 50)
        self.MAX_PDF_PAGES: int = _env_int("MAX_PDF_PAGES", 200)
        self.MAX_CONCURRENT_JOBS: int = _env_int("MAX_CONCURRENT_JOBS", 2)
        self.PROCESSING_TIMEOUT: int = _env_int("PROCESSING_TIMEOUT", 180)

        # ------------------------------------------------------------------
        # PDF → HEIC
        # ------------------------------------------------------------------
        self.DEFAULT_PDF_DPI: int = _env_int("DEFAULT_PDF_DPI", 200)
        self.DEFAULT_HEIC_QUALITY: int = _env_int("DEFAULT_HEIC_QUALITY", 90)

        # ------------------------------------------------------------------
        # PDF → long image
        # ------------------------------------------------------------------
        self.LONG_IMAGE_DPI: int = _env_int("LONG_IMAGE_DPI", 150)
        self.LONG_IMAGE_QUALITY: int = _env_int("LONG_IMAGE_QUALITY", 90)
        self.LONG_IMAGE_MAX_PAGES: int = _env_int("LONG_IMAGE_MAX_PAGES", 100)
        self.LONG_IMAGE_MAX_PIXELS: int = _env_int("LONG_IMAGE_MAX_PIXELS", 100_000_000)
        self.LONG_IMAGE_MAX_DIMENSION: int = _env_int("LONG_IMAGE_MAX_DIMENSION", 65_000)

        # ------------------------------------------------------------------
        # HEIC → PDF
        # ------------------------------------------------------------------
        self.HEIC_PDF_DPI: int = _env_int("HEIC_PDF_DPI", 150)
        self.HEIC_PDF_QUALITY: int = _env_int("HEIC_PDF_QUALITY", 90)
        self.MAX_HEIC_FILES: int = _env_int("MAX_HEIC_FILES", 50)
        self.MAX_HEIC_FILE_SIZE_MB: int = _env_int("MAX_HEIC_FILE_SIZE_MB", 50)
        self.MAX_TOTAL_UPLOAD_SIZE_MB: int = _env_int("MAX_TOTAL_UPLOAD_SIZE_MB", 500)
        self.MAX_IMAGE_PIXELS: int = _env_int("MAX_IMAGE_PIXELS", 50_000_000)

        # Compatibility aliases used by older code
        self.HEIC_PDF_MAX_FILES: int = self.MAX_HEIC_FILES
        self.HEIC_PDF_MAX_PIXELS: int = self.MAX_IMAGE_PIXELS

        # ------------------------------------------------------------------
        # PDF → PPTX
        # ------------------------------------------------------------------
        self.PDF_TO_PPTX_RENDER_DPI: int = _env_int(
            "PDF_TO_PPTX_RENDER_DPI",
            _env_int("PPTX_RENDER_DPI", 150),
        )
        self.PPTX_RENDER_DPI: int = self.PDF_TO_PPTX_RENDER_DPI
        self.PPTX_IMAGE_FORMAT: str = _env("PPTX_IMAGE_FORMAT", "jpeg")
        self.PPTX_JPEG_QUALITY: int = _env_int("PPTX_JPEG_QUALITY", 90)
        self.PPTX_MAX_PDF_SIZE_MB: int = _env_int(
            "PDF_TO_PPTX_MAX_FILE_SIZE_MB",
            _env_int("PPTX_MAX_PDF_SIZE_MB", 100),
        )
        self.PPTX_MAX_PAGES: int = _env_int(
            "PDF_TO_PPTX_MAX_PAGES",
            _env_int("PPTX_MAX_PAGES", 300),
        )
        self.PPTX_MAX_PIXELS_PER_PAGE: int = _env_int("PPTX_MAX_PIXELS_PER_PAGE", 40_000_000)

        self.PDF_TO_PPTX_DEFAULT_FONT: str = _env("PDF_TO_PPTX_DEFAULT_FONT", "Calibri")
        self.PDF_TO_PPTX_OCR_ENABLED: bool = _env_bool("PDF_TO_PPTX_OCR_ENABLED", True)
        self.PDF_TO_PPTX_OCR_LANGUAGES: str = _env("PDF_TO_PPTX_OCR_LANGUAGES", "eng,ben")
        self.PDF_TO_PPTX_EXTRACT_IMAGES: bool = _env_bool("PDF_TO_PPTX_EXTRACT_IMAGES", True)
        self.PDF_TO_PPTX_EXTRACT_SHAPES: bool = _env_bool("PDF_TO_PPTX_EXTRACT_SHAPES", True)
        self.PDF_TO_PPTX_DETECT_TABLES: bool = _env_bool("PDF_TO_PPTX_DETECT_TABLES", True)
        self.PDF_TO_PPTX_TIMEOUT_SECONDS: int = _env_int("PDF_TO_PPTX_TIMEOUT_SECONDS", 300)

        # ------------------------------------------------------------------
        # PPT/PPTX → PDF (LibreOffice)
        # ------------------------------------------------------------------
        self.PPTX_PDF_SOFFICE_PATH: str = _env("PPTX_PDF_SOFFICE_PATH", "")
        self.PPTX_PDF_TIMEOUT_SECONDS: int = _env_int("PPTX_PDF_TIMEOUT_SECONDS", 120)
        self.PPTX_PDF_MAX_FILE_MB: int = _env_int("PPTX_PDF_MAX_FILE_MB", 100)
        self.PPTX_PDF_MAX_SLIDES: int = _env_int("PPTX_PDF_MAX_SLIDES", 300)
        self.PPTX_PDF_MAX_UNCOMPRESSED_MB: int = _env_int("PPTX_PDF_MAX_UNCOMPRESSED_MB", 500)
        self.PPTX_PDF_MAX_CONCURRENT: int = _env_int("PPTX_PDF_MAX_CONCURRENT", 2)
        self.PPTX_PDF_QUEUE_WAIT_SECONDS: int = _env_int("PPTX_PDF_QUEUE_WAIT_SECONDS", 30)
        self.PPTX_PDF_MAX_ZIP_ENTRIES: int = _env_int("PPTX_PDF_MAX_ZIP_ENTRIES", 5000)
        self.PPTX_PDF_MAX_OUTPUT_MB: int = _env_int("PPTX_PDF_MAX_OUTPUT_MB", 300)
        self.PPTX_PDF_STALE_DIR_MINUTES: int = _env_int("PPTX_PDF_STALE_DIR_MINUTES", 60)

        # ------------------------------------------------------------------
        # PDF → embedded images ZIP
        # ------------------------------------------------------------------
        self.PDF_IMAGE_EXTRACT_DIRNAME: str = "pdf_image_extract"
        self.PDF_IMAGE_EXTRACT_TIMEOUT: int = _env_int("PDF_IMAGE_EXTRACT_TIMEOUT", 60)
        self.PDF_IMAGE_MAX_PAGES: int = _env_int("PDF_IMAGE_MAX_PAGES", 2000)
        self.PDF_IMAGE_MAX_IMAGES: int = _env_int("PDF_IMAGE_MAX_IMAGES", 5000)
        self.PDF_IMAGE_MAX_PIXELS: int = _env_int("PDF_IMAGE_MAX_PIXELS", 50_000_000)
        self.PDF_IMAGE_MAX_OUTPUT_MB: int = _env_int("PDF_IMAGE_MAX_OUTPUT_MB", 500)
        self.PDF_IMAGE_JOB_TTL_SECONDS: int = _env_int("PDF_IMAGE_JOB_TTL_SECONDS", 3600)
        self.PDF_IMAGE_APPLY_SOFT_MASKS: bool = _env_bool("PDF_IMAGE_APPLY_SOFT_MASKS", True)
        self.PDF_IMAGE_JPEG_QUALITY: int = _env_int("PDF_IMAGE_JPEG_QUALITY", 95)
        self.PDF_IMAGE_WEBP_QUALITY: int = _env_int("PDF_IMAGE_WEBP_QUALITY", 95)
        self.PDF_IMAGE_PNG_QUALITY: int = _env_int("PDF_IMAGE_PNG_QUALITY", 95)
        self.PDF_IMAGE_HEIC_QUALITY: int = _env_int("PDF_IMAGE_HEIC_QUALITY", 90)

        # ------------------------------------------------------------------
        # PDF flatten
        # ------------------------------------------------------------------
        self.PDF_FLATTEN_DIRNAME: str = "pdf_flatten"
        self.PDF_FLATTEN_TIMEOUT: int = _env_int("PDF_FLATTEN_TIMEOUT", 60)
        self.PDF_FLATTEN_MAX_PAGES: int = _env_int("PDF_FLATTEN_MAX_PAGES", 2000)
        self.PDF_FLATTEN_JOB_TTL_SECONDS: int = _env_int("PDF_FLATTEN_JOB_TTL_SECONDS", 3600)
        self.PDF_FLATTEN_ALLOW_SIGNED: bool = _env_bool("PDF_FLATTEN_ALLOW_SIGNED", False)
        self.PDF_FLATTEN_ANNOTATIONS: bool = _env_bool("PDF_FLATTEN_ANNOTATIONS", True)

        # ------------------------------------------------------------------
        # PDF table extraction
        # ------------------------------------------------------------------
        self.PDF_TABLES_DIRNAME: str = "pdf_tables"
        self.PDF_TABLES_JOB_TTL_SECONDS: int = _env_int("PDF_TABLES_JOB_TTL_SECONDS", 3600)
        self.MAX_TABLES: int = _env_int("MAX_TABLES", 500)
        self.MAX_ROWS_PER_TABLE: int = _env_int("MAX_ROWS_PER_TABLE", 5000)
        self.MAX_COLUMNS_PER_TABLE: int = _env_int("MAX_COLUMNS_PER_TABLE", 50)
        self.TABLE_MAX_PAGE_DIMENSION_PT: int = _env_int("TABLE_MAX_PAGE_DIMENSION_PT", 14400)
        self.TABLE_EXTRACTION_TIMEOUT: int = _env_int("TABLE_EXTRACTION_TIMEOUT", 120)
        self.TABLE_BORDERLESS_DETECTION: bool = _env_bool("TABLE_BORDERLESS_DETECTION", True)
        self.TABLE_CONTINUATION_EDGE_RATIO: float = _env_float("TABLE_CONTINUATION_EDGE_RATIO", 0.25)
        self.TABLE_COLUMN_ALIGN_TOLERANCE: float = _env_float("TABLE_COLUMN_ALIGN_TOLERANCE", 0.02)

        # Table export
        self.TABLE_CSV_BOM: bool = _env_bool("TABLE_CSV_BOM", True)
        self.TABLE_IMAGE_MAX_ROWS: int = _env_int("TABLE_IMAGE_MAX_ROWS", 200)
        self.TABLE_IMAGE_MAX_PIXELS: int = _env_int("TABLE_IMAGE_MAX_PIXELS", 20_000_000)
        self.TABLE_IMAGE_FONT_PATH: str = _env("TABLE_IMAGE_FONT_PATH", "")
        self.TABLE_IMAGE_BENGALI_FONT_PATH: str = _env("TABLE_IMAGE_BENGALI_FONT_PATH", "")

        # ------------------------------------------------------------------
        # OCR (shared by tables, searchable PDF, PPTX, etc.)
        # ------------------------------------------------------------------
        self.OCR_ENABLED: bool = _env_bool("OCR_ENABLED", True)
        self.OCR_LANGUAGE: str = _env("OCR_LANGUAGE", "eng+ben")   # Bengali + English
        self.OCR_TIMEOUT: int = _env_int("OCR_TIMEOUT", 120)
        self.OCR_DPI: int = _env_int("OCR_DPI", 200)
        self.OCR_MAX_PAGES: int = _env_int("OCR_MAX_PAGES", 30)
        self.OCR_MAX_PIXELS: int = _env_int("OCR_MAX_PIXELS", 40_000_000)
        self.OCR_MIN_WORDS: int = _env_int("OCR_MIN_WORDS", 5)
        self.OCR_FONT_PATH: str = _env("OCR_FONT_PATH", "")

        # ------------------------------------------------------------------
        # Searchable PDF / make-searchable
        # ------------------------------------------------------------------
        self.SEARCHABLE_DIRNAME: str = "pdf_searchable"
        self.SEARCHABLE_TIMEOUT: int = _env_int("SEARCHABLE_TIMEOUT", 180)
        self.SEARCHABLE_DPI: int = _env_int("SEARCHABLE_DPI", 150)
        self.SEARCHABLE_JOB_TTL_SECONDS: int = _env_int("SEARCHABLE_JOB_TTL_SECONDS", 3600)

        # ------------------------------------------------------------------
        # Deskew
        # ------------------------------------------------------------------
        self.DESKEW_DIRNAME: str = "pdf_deskew"
        self.DESKEW_TIMEOUT: int = _env_int("DESKEW_TIMEOUT", 120)
        self.DESKEW_DPI: int = _env_int("DESKEW_DPI", 120)
        self.DESKEW_MIN_CONFIDENCE: float = _env_float("DESKEW_MIN_CONFIDENCE", 0.4)
        self.DESKEW_MAX_ANGLE: float = _env_float("DESKEW_MAX_ANGLE", 15.0)
        self.DESKEW_JOB_TTL_SECONDS: int = _env_int("DESKEW_JOB_TTL_SECONDS", 3600)

        # ------------------------------------------------------------------
        # Auto-rotate
        # ------------------------------------------------------------------
        self.ORIENT_DIRNAME: str = "pdf_orient"
        self.ORIENT_TIMEOUT: int = _env_int("ORIENT_TIMEOUT", 120)
        self.ORIENT_DPI: int = _env_int("ORIENT_DPI", 100)
        self.ORIENT_MIN_CONFIDENCE: float = _env_float("ORIENT_MIN_CONFIDENCE", 0.5)
        self.ORIENT_JOB_TTL_SECONDS: int = _env_int("ORIENT_JOB_TTL_SECONDS", 3600)

        # ------------------------------------------------------------------
        # Enhance
        # ------------------------------------------------------------------
        self.ENHANCE_DIRNAME: str = "pdf_enhance"
        self.ENHANCE_TIMEOUT: int = _env_int("ENHANCE_TIMEOUT", 120)
        self.ENHANCE_DPI: int = _env_int("ENHANCE_DPI", 130)
        self.ENHANCE_DEFAULT_CONTRAST: float = _env_float("ENHANCE_DEFAULT_CONTRAST", 1.15)
        self.ENHANCE_DEFAULT_BRIGHTNESS: float = _env_float("ENHANCE_DEFAULT_BRIGHTNESS", 1.05)
        self.ENHANCE_DEFAULT_SHARPEN: float = _env_float("ENHANCE_DEFAULT_SHARPEN", 0.3)
        self.ENHANCE_JOB_TTL_SECONDS: int = _env_int("ENHANCE_JOB_TTL_SECONDS", 3600)

        # ------------------------------------------------------------------
        # PDF Compare
        # ------------------------------------------------------------------
        self.COMPARE_DIRNAME: str = "pdf_compare"
        self.COMPARE_TIMEOUT: int = _env_int("COMPARE_TIMEOUT", 180)
        self.COMPARE_RENDER_DPI: int = _env_int("COMPARE_RENDER_DPI", 100)
        self.PDF_COMPARE_VISUAL_THRESHOLD: float = _env_float("PDF_COMPARE_VISUAL_THRESHOLD", 0.12)
        self.PDF_COMPARE_MIN_CHANGE_AREA: int = _env_int("PDF_COMPARE_MIN_CHANGE_AREA", 500)
        self.COMPARE_JOB_TTL_SECONDS: int = _env_int("COMPARE_JOB_TTL_SECONDS", 3600)

        # ------------------------------------------------------------------
        # Rendering safety (shared)
        # ------------------------------------------------------------------
        self.MAX_RENDER_DPI: int = _env_int("MAX_RENDER_DPI", 150)
        self.MAX_PAGE_PIXELS: int = _env_int("MAX_PAGE_PIXELS", 4_000_000)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def max_pdf_size_bytes(self) -> int:
        return self.MAX_PDF_SIZE_MB * 1024 * 1024

    def ensure_dirs(self) -> None:
        """Create output / temp roots if they do not exist."""
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


# Backwards-compatible module-level singleton used by older code:
#   from app.config import settings
settings = get_settings()





# import os
# from pathlib import Path
# from dotenv import load_dotenv

# load_dotenv()


# class Settings:

#     env_int = lambda var_name, default: int(os.getenv(var_name, str(default)))
#     env_bool = lambda var_name, default: os.getenv(var_name, str(default)).lower() in ("true", "1", "yes")

#     OUTPUT_DIR: Path = Path(
#         os.getenv("OUTPUT_DIR", str(Path(__file__).resolve().parent.parent / "converted_files"))
#     )

#     # PDF to HEIC conversion settings

#     MAX_PDF_SIZE_MB: int = int(os.getenv("MAX_PDF_SIZE_MB", "50"))
#     MAX_PDF_PAGES: int = int(os.getenv("MAX_PDF_PAGES", "200"))
#     DEFAULT_PDF_DPI: int = int(os.getenv("DEFAULT_PDF_DPI", "200"))
#     DEFAULT_HEIC_QUALITY: int = int(os.getenv("DEFAULT_HEIC_QUALITY", "90"))

#     # PDF -> long image
#     LONG_IMAGE_DPI: int = int(os.getenv("LONG_IMAGE_DPI", "150"))
#     LONG_IMAGE_QUALITY: int = int(os.getenv("LONG_IMAGE_QUALITY", "90"))  # JPEG/HEIC
#     LONG_IMAGE_MAX_PAGES: int = int(os.getenv("LONG_IMAGE_MAX_PAGES", "100"))
#     LONG_IMAGE_MAX_PIXELS: int = int(os.getenv("LONG_IMAGE_MAX_PIXELS", "100000000"))
#     LONG_IMAGE_MAX_DIMENSION: int = int(os.getenv("LONG_IMAGE_MAX_DIMENSION", "65000"))


#      # HEIC -> PDF
#     HEIC_PDF_DPI: int = int(os.getenv("HEIC_PDF_DPI", "150"))
#     HEIC_PDF_QUALITY: int = int(os.getenv("HEIC_PDF_QUALITY", "90"))
#     MAX_HEIC_FILES: int = int(os.getenv("MAX_HEIC_FILES", "50"))
#     MAX_HEIC_FILE_SIZE_MB: int = int(os.getenv("MAX_HEIC_FILE_SIZE_MB", "50"))
#     MAX_TOTAL_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_TOTAL_UPLOAD_SIZE_MB", "500"))
#     MAX_IMAGE_PIXELS: int = int(os.getenv("MAX_IMAGE_PIXELS", "50000000"))


#     # PDF -> PPTX
#     PDF_TO_PPTX_RENDER_DPI: int = int(os.getenv("PDF_TO_PPTX_RENDER_DPI", os.getenv("PPTX_RENDER_DPI", "150")))
#     PPTX_RENDER_DPI: int = PDF_TO_PPTX_RENDER_DPI
#     PPTX_IMAGE_FORMAT: str = os.getenv("PPTX_IMAGE_FORMAT", "jpeg")  # "jpeg" or "png"
#     PPTX_JPEG_QUALITY: int = int(os.getenv("PPTX_JPEG_QUALITY", "90"))
#     PPTX_MAX_PDF_SIZE_MB: int = int(os.getenv("PDF_TO_PPTX_MAX_FILE_SIZE_MB", os.getenv("PPTX_MAX_PDF_SIZE_MB", "100")))
#     PPTX_MAX_PAGES: int = int(os.getenv("PDF_TO_PPTX_MAX_PAGES", os.getenv("PPTX_MAX_PAGES", "300")))
#     PPTX_MAX_PIXELS_PER_PAGE: int = int(os.getenv("PPTX_MAX_PIXELS_PER_PAGE", "40000000"))

#     PDF_TO_PPTX_DEFAULT_FONT: str = os.getenv("PDF_TO_PPTX_DEFAULT_FONT", "Calibri")
#     PDF_TO_PPTX_OCR_ENABLED: bool = os.getenv("PDF_TO_PPTX_OCR_ENABLED", "true").lower() in ("true", "1", "yes")
#     PDF_TO_PPTX_OCR_LANGUAGES: str = os.getenv("PDF_TO_PPTX_OCR_LANGUAGES", "eng,ben")
#     PDF_TO_PPTX_EXTRACT_IMAGES: bool = os.getenv("PDF_TO_PPTX_EXTRACT_IMAGES", "true").lower() in ("true", "1", "yes")
#     PDF_TO_PPTX_EXTRACT_SHAPES: bool = os.getenv("PDF_TO_PPTX_EXTRACT_SHAPES", "true").lower() in ("true", "1", "yes")
#     PDF_TO_PPTX_DETECT_TABLES: bool = os.getenv("PDF_TO_PPTX_DETECT_TABLES", "true").lower() in ("true", "1", "yes")
#     PDF_TO_PPTX_TIMEOUT_SECONDS: int = int(os.getenv("PDF_TO_PPTX_TIMEOUT_SECONDS", "300"))

#     # HEIC compatibility aliases
#     HEIC_PDF_MAX_FILES: int = int(os.getenv("MAX_HEIC_FILES", "50"))
#     HEIC_PDF_MAX_PIXELS: int = int(os.getenv("MAX_IMAGE_PIXELS", "50000000"))


#     # PPT/PPTX -> PDF (requires LibreOffice)
#     PPTX_PDF_SOFFICE_PATH: str = os.getenv("PPTX_PDF_SOFFICE_PATH", "")
#     PPTX_PDF_TIMEOUT_SECONDS: int = int(os.getenv("PPTX_PDF_TIMEOUT_SECONDS", "120"))
#     PPTX_PDF_MAX_FILE_MB: int = int(os.getenv("PPTX_PDF_MAX_FILE_MB", "100"))
#     PPTX_PDF_MAX_SLIDES: int = int(os.getenv("PPTX_PDF_MAX_SLIDES", "300"))
#     PPTX_PDF_MAX_UNCOMPRESSED_MB: int = int(os.getenv("PPTX_PDF_MAX_UNCOMPRESSED_MB", "500"))
#     PPTX_PDF_MAX_CONCURRENT: int = int(os.getenv("PPTX_PDF_MAX_CONCURRENT", "2"))
#     PPTX_PDF_QUEUE_WAIT_SECONDS: int = int(os.getenv("PPTX_PDF_QUEUE_WAIT_SECONDS", "30"))
#     PPTX_PDF_MAX_ZIP_ENTRIES: int = int(os.getenv("PPTX_PDF_MAX_ZIP_ENTRIES", "5000"))
#     PPTX_PDF_MAX_OUTPUT_MB: int = int(os.getenv("PPTX_PDF_MAX_OUTPUT_MB", "300"))
#     PPTX_PDF_STALE_DIR_MINUTES: int = int(os.getenv("PPTX_PDF_STALE_DIR_MINUTES", "60"))


    
#     # --- PDF -> embedded images ZIP ---
#     PDF_IMAGE_EXTRACT_DIRNAME = "pdf_image_extract"
#     MAX_PDF_SIZE_MB = env_int("MAX_PDF_SIZE_MB", 50)
#     PDF_IMAGE_EXTRACT_TIMEOUT = env_int("PDF_IMAGE_EXTRACT_TIMEOUT", 60)        # seconds
#     PDF_IMAGE_MAX_PAGES = env_int("PDF_IMAGE_MAX_PAGES", 2000)
#     PDF_IMAGE_MAX_IMAGES = env_int("PDF_IMAGE_MAX_IMAGES", 5000)
#     PDF_IMAGE_MAX_PIXELS = env_int("PDF_IMAGE_MAX_PIXELS", 50_000_000)          # per image
#     PDF_IMAGE_MAX_OUTPUT_MB = env_int("PDF_IMAGE_MAX_OUTPUT_MB", 500)           # total extracted bytes
#     PDF_IMAGE_JOB_TTL_SECONDS = env_int("PDF_IMAGE_JOB_TTL_SECONDS", 3600)      # orphan sweeper
#     PDF_IMAGE_APPLY_SOFT_MASKS = env_bool("PDF_IMAGE_APPLY_SOFT_MASKS", True)
#     PDF_IMAGE_JPEG_QUALITY = env_int("PDF_IMAGE_JPEG_QUALITY", 95)
#     PDF_IMAGE_WEBP_QUALITY = env_int("PDF_IMAGE_WEBP_QUALITY", 95)
#     PDF_IMAGE_PNG_QUALITY = env_int("PDF_IMAGE_PNG_QUALITY", 95)
#     PDF_IMAGE_HEIC_QUALITY = env_int("PDF_IMAGE_HEIC_QUALITY", 90)


#     # --- PDF flatten ---
#     PDF_FLATTEN_DIRNAME = "pdf_flatten"
#     PDF_FLATTEN_TIMEOUT = env_int("PDF_FLATTEN_TIMEOUT", 60)                    # seconds, cooperative
#     PDF_FLATTEN_MAX_PAGES = env_int("PDF_FLATTEN_MAX_PAGES", 2000)
#     PDF_FLATTEN_JOB_TTL_SECONDS = env_int("PDF_FLATTEN_JOB_TTL_SECONDS", 3600)  # orphan sweeper
#     PDF_FLATTEN_ALLOW_SIGNED = env_bool("PDF_FLATTEN_ALLOW_SIGNED", False)      # True: strip signatures
#     PDF_FLATTEN_ANNOTATIONS = env_bool("PDF_FLATTEN_ANNOTATIONS", True)         # False: fields only



#     # --- PDF table extraction ---
#     PDF_TABLES_DIRNAME = "pdf_tables"
#     PDF_TABLES_JOB_TTL_SECONDS = env_int("PDF_TABLES_JOB_TTL_SECONDS", 3600)   # orphan sweeper
#     MAX_PDF_PAGES = env_int("MAX_PDF_PAGES", 500)                 # pages processed per request
#     MAX_TABLES = env_int("MAX_TABLES", 500)
#     MAX_ROWS_PER_TABLE = env_int("MAX_ROWS_PER_TABLE", 5000)
#     MAX_COLUMNS_PER_TABLE = env_int("MAX_COLUMNS_PER_TABLE", 50)
#     TABLE_MAX_PAGE_DIMENSION_PT = env_int("TABLE_MAX_PAGE_DIMENSION_PT", 14400)
#     TABLE_EXTRACTION_TIMEOUT = env_int("TABLE_EXTRACTION_TIMEOUT", 120)         # seconds, cooperative
#     TABLE_BORDERLESS_DETECTION = env_bool("TABLE_BORDERLESS_DETECTION", True)
#     TABLE_CONTINUATION_EDGE_RATIO = float(os.getenv("TABLE_CONTINUATION_EDGE_RATIO", "0.25"))
#     TABLE_COLUMN_ALIGN_TOLERANCE = float(os.getenv("TABLE_COLUMN_ALIGN_TOLERANCE", "0.02"))

#     # OCR (skip the first two if they already exist)
#     OCR_ENABLED = env_bool("OCR_ENABLED", True)
#     OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "eng")                # Bengali + English: "ben+eng"
#     OCR_TIMEOUT = env_int("OCR_TIMEOUT", 120)                     # cumulative OCR seconds per request
#     OCR_DPI = env_int("OCR_DPI", 200)
#     OCR_MAX_PAGES = env_int("OCR_MAX_PAGES", 30)
#     OCR_MAX_PIXELS = env_int("OCR_MAX_PIXELS", 40_000_000)
#     OCR_MIN_WORDS = env_int("OCR_MIN_WORDS", 5)                   # fewer words = "no usable text layer"

#     # Export
#     TABLE_CSV_BOM = env_bool("TABLE_CSV_BOM", True)
#     TABLE_IMAGE_MAX_ROWS = env_int("TABLE_IMAGE_MAX_ROWS", 200)
#     TABLE_IMAGE_MAX_PIXELS = env_int("TABLE_IMAGE_MAX_PIXELS", 20_000_000)
#     TABLE_IMAGE_FONT_PATH = os.getenv("TABLE_IMAGE_FONT_PATH", "")
#     TABLE_IMAGE_BENGALI_FONT_PATH = os.getenv("TABLE_IMAGE_BENGALI_FONT_PATH", "")

# settings = Settings()