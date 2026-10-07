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


def test_flatten_endpoint_with_granular_options(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    page = document.new_page()

    # Form field
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "test_name"
    widget.field_value = "Rahim Ahmed"
    widget.rect = pymupdf.Rect(50, 50, 200, 80)
    page.add_widget(widget)

    # Highlight annotation
    page.add_highlight_annot(pymupdf.Rect(50, 100, 200, 120))

    # Stamp annotation
    page.add_stamp_annot(pymupdf.Rect(50, 150, 200, 200), stamp=0)

    pdf_bytes = document.tobytes()
    document.close()

    # Test flattening only forms, keeping annotations and stamps
    response = client.post(
        "/api/v1/pdf/flatten",
        data={
            "flatten_forms": "true",
            "flatten_annotations": "false",
            "flatten_stamps": "false",
        },
        files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["x-flatten-form-fields"] == "1"

    flattened = pymupdf.open(stream=response.content, filetype="pdf")
    # Widgets baked into page text
    assert all(not list(p.widgets() or []) for p in flattened)
    assert "Rahim Ahmed" in flattened[0].get_text()
    # Annotations were kept
    annots = list(flattened[0].annots() or [])
    assert len(annots) >= 1
    flattened.close()


def test_full_pdf_flatten_makes_text_non_selectable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    page = document.new_page(width=500, height=700)
    page.insert_text((50, 100), "Sensitive Non-Selectable Data 12345", fontsize=14)

    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "account"
    widget.field_value = "ACC-9988"
    widget.rect = pymupdf.Rect(50, 150, 200, 180)
    page.add_widget(widget)

    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/flatten",
        data={
            "full_flatten": "true",
            "dpi": "100",
        },
        files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    flattened = pymupdf.open(stream=response.content, filetype="pdf")
    assert flattened.page_count == 1

    # In full flatten mode, text is 100% rasterized: NO selectable text exists
    text = flattened[0].get_text().strip()
    assert text == ""

    # No interactive widgets exist
    assert len(list(flattened[0].widgets() or [])) == 0

    # Image exists on page representing the rendered view
    assert len(flattened[0].get_images()) >= 1
    flattened.close()


