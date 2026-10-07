import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_enhance_preview_returns_first_page_with_selected_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    received_options = []

    def record_enhancement(image, **options):
        received_options.append(options)
        return image

    monkeypatch.setattr("app.routers.pdf_enhance.enhance_image", record_enhancement)
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/enhance/preview",
        params={
            "grayscale": "true",
            "contrast": "1.4",
            "brightness": "0.9",
            "sharpen": "0.7",
            "denoise": "true",
            "threshold": "false",
            "background_cleanup": "true",
        },
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(b"\xff\xd8")
    assert received_options == [
        {
            "grayscale": True,
            "contrast": 1.4,
            "brightness": 0.9,
            "sharpen": 0.7,
            "denoise": True,
            "threshold": False,
            "background_cleanup": True,
        }
    ]
