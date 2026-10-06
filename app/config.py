import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:

    env_int = lambda var_name, default: int(os.getenv(var_name, str(default)))
    env_bool = lambda var_name, default: os.getenv(var_name, str(default)).lower() in ("true", "1", "yes")

    OUTPUT_DIR: Path = Path(
        os.getenv("OUTPUT_DIR", str(Path(__file__).resolve().parent.parent / "converted_files"))
    )

    # PDF to HEIC conversion settings

    MAX_PDF_SIZE_MB: int = int(os.getenv("MAX_PDF_SIZE_MB", "50"))
    MAX_PDF_PAGES: int = int(os.getenv("MAX_PDF_PAGES", "200"))
    DEFAULT_PDF_DPI: int = int(os.getenv("DEFAULT_PDF_DPI", "200"))
    DEFAULT_HEIC_QUALITY: int = int(os.getenv("DEFAULT_HEIC_QUALITY", "90"))

    # PDF -> long image
    LONG_IMAGE_DPI: int = int(os.getenv("LONG_IMAGE_DPI", "150"))
    LONG_IMAGE_QUALITY: int = int(os.getenv("LONG_IMAGE_QUALITY", "90"))  # JPEG/HEIC
    LONG_IMAGE_MAX_PAGES: int = int(os.getenv("LONG_IMAGE_MAX_PAGES", "100"))
    LONG_IMAGE_MAX_PIXELS: int = int(os.getenv("LONG_IMAGE_MAX_PIXELS", "100000000"))
    LONG_IMAGE_MAX_DIMENSION: int = int(os.getenv("LONG_IMAGE_MAX_DIMENSION", "65000"))


     # HEIC -> PDF
    HEIC_PDF_DPI: int = int(os.getenv("HEIC_PDF_DPI", "150"))
    HEIC_PDF_QUALITY: int = int(os.getenv("HEIC_PDF_QUALITY", "90"))
    MAX_HEIC_FILES: int = int(os.getenv("MAX_HEIC_FILES", "50"))
    MAX_HEIC_FILE_SIZE_MB: int = int(os.getenv("MAX_HEIC_FILE_SIZE_MB", "50"))
    MAX_TOTAL_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_TOTAL_UPLOAD_SIZE_MB", "500"))
    MAX_IMAGE_PIXELS: int = int(os.getenv("MAX_IMAGE_PIXELS", "50000000"))


    # PDF -> PPTX
    PDF_TO_PPTX_RENDER_DPI: int = int(os.getenv("PDF_TO_PPTX_RENDER_DPI", os.getenv("PPTX_RENDER_DPI", "150")))
    PPTX_RENDER_DPI: int = PDF_TO_PPTX_RENDER_DPI
    PPTX_IMAGE_FORMAT: str = os.getenv("PPTX_IMAGE_FORMAT", "jpeg")  # "jpeg" or "png"
    PPTX_JPEG_QUALITY: int = int(os.getenv("PPTX_JPEG_QUALITY", "90"))
    PPTX_MAX_PDF_SIZE_MB: int = int(os.getenv("PDF_TO_PPTX_MAX_FILE_SIZE_MB", os.getenv("PPTX_MAX_PDF_SIZE_MB", "100")))
    PPTX_MAX_PAGES: int = int(os.getenv("PDF_TO_PPTX_MAX_PAGES", os.getenv("PPTX_MAX_PAGES", "300")))
    PPTX_MAX_PIXELS_PER_PAGE: int = int(os.getenv("PPTX_MAX_PIXELS_PER_PAGE", "40000000"))

    PDF_TO_PPTX_DEFAULT_FONT: str = os.getenv("PDF_TO_PPTX_DEFAULT_FONT", "Calibri")
    PDF_TO_PPTX_OCR_ENABLED: bool = os.getenv("PDF_TO_PPTX_OCR_ENABLED", "true").lower() in ("true", "1", "yes")
    PDF_TO_PPTX_OCR_LANGUAGES: str = os.getenv("PDF_TO_PPTX_OCR_LANGUAGES", "eng,ben")
    PDF_TO_PPTX_EXTRACT_IMAGES: bool = os.getenv("PDF_TO_PPTX_EXTRACT_IMAGES", "true").lower() in ("true", "1", "yes")
    PDF_TO_PPTX_EXTRACT_SHAPES: bool = os.getenv("PDF_TO_PPTX_EXTRACT_SHAPES", "true").lower() in ("true", "1", "yes")
    PDF_TO_PPTX_DETECT_TABLES: bool = os.getenv("PDF_TO_PPTX_DETECT_TABLES", "true").lower() in ("true", "1", "yes")
    PDF_TO_PPTX_TIMEOUT_SECONDS: int = int(os.getenv("PDF_TO_PPTX_TIMEOUT_SECONDS", "300"))

    # HEIC compatibility aliases
    HEIC_PDF_MAX_FILES: int = int(os.getenv("MAX_HEIC_FILES", "50"))
    HEIC_PDF_MAX_PIXELS: int = int(os.getenv("MAX_IMAGE_PIXELS", "50000000"))


    # PPT/PPTX -> PDF (requires LibreOffice)
    PPTX_PDF_SOFFICE_PATH: str = os.getenv("PPTX_PDF_SOFFICE_PATH", "")
    PPTX_PDF_TIMEOUT_SECONDS: int = int(os.getenv("PPTX_PDF_TIMEOUT_SECONDS", "120"))
    PPTX_PDF_MAX_FILE_MB: int = int(os.getenv("PPTX_PDF_MAX_FILE_MB", "100"))
    PPTX_PDF_MAX_SLIDES: int = int(os.getenv("PPTX_PDF_MAX_SLIDES", "300"))
    PPTX_PDF_MAX_UNCOMPRESSED_MB: int = int(os.getenv("PPTX_PDF_MAX_UNCOMPRESSED_MB", "500"))
    PPTX_PDF_MAX_CONCURRENT: int = int(os.getenv("PPTX_PDF_MAX_CONCURRENT", "2"))
    PPTX_PDF_QUEUE_WAIT_SECONDS: int = int(os.getenv("PPTX_PDF_QUEUE_WAIT_SECONDS", "30"))
    PPTX_PDF_MAX_ZIP_ENTRIES: int = int(os.getenv("PPTX_PDF_MAX_ZIP_ENTRIES", "5000"))
    PPTX_PDF_MAX_OUTPUT_MB: int = int(os.getenv("PPTX_PDF_MAX_OUTPUT_MB", "300"))
    PPTX_PDF_STALE_DIR_MINUTES: int = int(os.getenv("PPTX_PDF_STALE_DIR_MINUTES", "60"))


    
    # --- PDF -> embedded images ZIP ---
    PDF_IMAGE_EXTRACT_DIRNAME = "pdf_image_extract"
    MAX_PDF_SIZE_MB = env_int("MAX_PDF_SIZE_MB", 50)
    PDF_IMAGE_EXTRACT_TIMEOUT = env_int("PDF_IMAGE_EXTRACT_TIMEOUT", 60)        # seconds
    PDF_IMAGE_MAX_PAGES = env_int("PDF_IMAGE_MAX_PAGES", 2000)
    PDF_IMAGE_MAX_IMAGES = env_int("PDF_IMAGE_MAX_IMAGES", 5000)
    PDF_IMAGE_MAX_PIXELS = env_int("PDF_IMAGE_MAX_PIXELS", 50_000_000)          # per image
    PDF_IMAGE_MAX_OUTPUT_MB = env_int("PDF_IMAGE_MAX_OUTPUT_MB", 500)           # total extracted bytes
    PDF_IMAGE_JOB_TTL_SECONDS = env_int("PDF_IMAGE_JOB_TTL_SECONDS", 3600)      # orphan sweeper
    PDF_IMAGE_APPLY_SOFT_MASKS = env_bool("PDF_IMAGE_APPLY_SOFT_MASKS", True)
    PDF_IMAGE_JPEG_QUALITY = env_int("PDF_IMAGE_JPEG_QUALITY", 95)
    PDF_IMAGE_WEBP_QUALITY = env_int("PDF_IMAGE_WEBP_QUALITY", 95)
    PDF_IMAGE_PNG_QUALITY = env_int("PDF_IMAGE_PNG_QUALITY", 95)
    PDF_IMAGE_HEIC_QUALITY = env_int("PDF_IMAGE_HEIC_QUALITY", 90)


    # --- PDF flatten ---
    PDF_FLATTEN_DIRNAME = "pdf_flatten"
    PDF_FLATTEN_TIMEOUT = env_int("PDF_FLATTEN_TIMEOUT", 60)                    # seconds, cooperative
    PDF_FLATTEN_MAX_PAGES = env_int("PDF_FLATTEN_MAX_PAGES", 2000)
    PDF_FLATTEN_JOB_TTL_SECONDS = env_int("PDF_FLATTEN_JOB_TTL_SECONDS", 3600)  # orphan sweeper
    PDF_FLATTEN_ALLOW_SIGNED = env_bool("PDF_FLATTEN_ALLOW_SIGNED", False)      # True: strip signatures
    PDF_FLATTEN_ANNOTATIONS = env_bool("PDF_FLATTEN_ANNOTATIONS", True)         # False: fields only



    # --- PDF table extraction ---
    PDF_TABLES_DIRNAME = "pdf_tables"
    PDF_TABLES_JOB_TTL_SECONDS = env_int("PDF_TABLES_JOB_TTL_SECONDS", 3600)   # orphan sweeper
    MAX_PDF_PAGES = env_int("MAX_PDF_PAGES", 500)                 # pages processed per request
    MAX_TABLES = env_int("MAX_TABLES", 500)
    MAX_ROWS_PER_TABLE = env_int("MAX_ROWS_PER_TABLE", 5000)
    MAX_COLUMNS_PER_TABLE = env_int("MAX_COLUMNS_PER_TABLE", 50)
    TABLE_MAX_PAGE_DIMENSION_PT = env_int("TABLE_MAX_PAGE_DIMENSION_PT", 14400)
    TABLE_EXTRACTION_TIMEOUT = env_int("TABLE_EXTRACTION_TIMEOUT", 120)         # seconds, cooperative
    TABLE_BORDERLESS_DETECTION = env_bool("TABLE_BORDERLESS_DETECTION", True)
    TABLE_CONTINUATION_EDGE_RATIO = float(os.getenv("TABLE_CONTINUATION_EDGE_RATIO", "0.25"))
    TABLE_COLUMN_ALIGN_TOLERANCE = float(os.getenv("TABLE_COLUMN_ALIGN_TOLERANCE", "0.02"))

    # OCR (skip the first two if they already exist)
    OCR_ENABLED = env_bool("OCR_ENABLED", True)
    OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "eng")                # Bengali + English: "ben+eng"
    OCR_TIMEOUT = env_int("OCR_TIMEOUT", 120)                     # cumulative OCR seconds per request
    OCR_DPI = env_int("OCR_DPI", 200)
    OCR_MAX_PAGES = env_int("OCR_MAX_PAGES", 30)
    OCR_MAX_PIXELS = env_int("OCR_MAX_PIXELS", 40_000_000)
    OCR_MIN_WORDS = env_int("OCR_MIN_WORDS", 5)                   # fewer words = "no usable text layer"

    # Export
    TABLE_CSV_BOM = env_bool("TABLE_CSV_BOM", True)
    TABLE_IMAGE_MAX_ROWS = env_int("TABLE_IMAGE_MAX_ROWS", 200)
    TABLE_IMAGE_MAX_PIXELS = env_int("TABLE_IMAGE_MAX_PIXELS", 20_000_000)
    TABLE_IMAGE_FONT_PATH = os.getenv("TABLE_IMAGE_FONT_PATH", "")
    TABLE_IMAGE_BENGALI_FONT_PATH = os.getenv("TABLE_IMAGE_BENGALI_FONT_PATH", "")

settings = Settings()