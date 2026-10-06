from io import BytesIO
from zipfile import ZipFile

import pymupdf
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app
from app.services.pdf_extract_images import ExtractionSettings, MIB

client = TestClient(app)


def test_extraction_settings_use_application_config():
    extraction_settings = ExtractionSettings.from_config()

    assert extraction_settings.output_root == settings.OUTPUT_DIR / settings.PDF_IMAGE_EXTRACT_DIRNAME
    assert extraction_settings.max_pdf_bytes == settings.MAX_PDF_SIZE_MB * MIB
    assert extraction_settings.timeout_seconds == settings.PDF_IMAGE_EXTRACT_TIMEOUT


def test_extract_images_accepts_output_format_as_multipart_form_field(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    jpeg = BytesIO()
    Image.new("RGB", (2, 2), "red").save(jpeg, format="JPEG")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(pymupdf.Rect(0, 0, 20, 20), stream=jpeg.getvalue())
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/extract-images",
        files={"file": ("images.pdf", pdf_bytes, "application/pdf")},
        data={"output_format": "png"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["x-output-format"] == "png"
    assert response.headers["x-extracted-image-count"] == "1"
    with ZipFile(BytesIO(response.content)) as archive:
        image_name = archive.namelist()[0]
        assert image_name.endswith(".png")
        assert archive.read(image_name).startswith(b"\x89PNG\r\n\x1a\n")
