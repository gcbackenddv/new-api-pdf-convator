import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_flatten_endpoint_returns_downloaded_pdf_with_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Flatten test")
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/flatten",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].endswith('filename="flattened-document.pdf"')
    assert response.headers["x-flatten-form-fields"] == "0"
    assert response.headers["x-flatten-annotations"] == "0"

    flattened = pymupdf.open(stream=response.content, filetype="pdf")
    assert flattened.page_count == 1
    assert "Flatten test" in flattened[0].get_text()
    flattened.close()


def test_flatten_endpoint_bakes_form_field_into_page_content(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    page = document.new_page()
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "verification_field"
    widget.field_value = "Flattened form value"
    widget.rect = pymupdf.Rect(72, 72, 250, 100)
    page.add_widget(widget)
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/flatten",
        files={"file": ("form.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["x-flatten-form-fields"] == "1"

    flattened = pymupdf.open(stream=response.content, filetype="pdf")
    assert all(not list(page.widgets() or []) for page in flattened)
    assert "Flattened form value" in flattened[0].get_text()
    flattened.close()
