import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:

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



settings = Settings()