import io
import json
import numpy as np
from PIL import Image
import pymupdf as fitz
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_remove_blank_pages_success(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    # Page 1: content
    p1 = doc.new_page()
    p1.insert_text((72, 72), "First Page Content")
    # Page 2: genuinely blank
    doc.new_page()
    # Page 3: content
    p3 = doc.new_page()
    p3.insert_text((72, 72), "Third Page Content")

    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/pdf/remove-blank-pages",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-original-pages"] == "3"
    assert response.headers["x-removed-pages"] == "1"
    assert response.headers["x-remaining-pages"] == "2"
    assert json.loads(response.headers["x-removed-page-numbers"]) == [2]

    cleaned_doc = fitz.open(stream=response.content, filetype="pdf")
    assert cleaned_doc.page_count == 2
    assert "First Page Content" in cleaned_doc[0].get_text()
    assert "Third Page Content" in cleaned_doc[1].get_text()
    cleaned_doc.close()


def test_remove_blank_pages_none_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Content 1")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Content 2")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/pdf/remove-blank-pages",
        files={"file": ("all_valid.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers["x-removed-pages"] == "0"
    assert response.headers["x-remaining-pages"] == "2"
    assert json.loads(response.headers["x-removed-page-numbers"]) == []

    cleaned_doc = fitz.open(stream=response.content, filetype="pdf")
    assert cleaned_doc.page_count == 2
    cleaned_doc.close()


def test_remove_blank_pages_all_blank_returns_422(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/pdf/remove-blank-pages",
        files={"file": ("all_blank.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 422
    assert "blank" in response.json()["detail"].lower()


def test_remove_blank_pages_scanned_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()

    # Scanned Page 1: Paper background with slight sensor noise (blank sheet)
    h, w = 400, 300
    blank_scan = np.random.normal(250, 1.5, (h, w)).clip(0, 255).astype(np.uint8)
    blank_scan[0:3, :] = 0  # Feeder line
    buf_blank = io.BytesIO()
    Image.fromarray(blank_scan).save(buf_blank, format="JPEG", quality=85)
    p1 = doc.new_page(width=300, height=400)
    p1.insert_image(p1.rect, stream=buf_blank.getvalue())

    # Scanned Page 2: Contains meaningful document content/writing
    content_scan = blank_scan.copy()
    content_scan[150:200, 100:200] = 0  # Black ink block / signature / text
    buf_content = io.BytesIO()
    Image.fromarray(content_scan).save(buf_content, format="JPEG", quality=85)
    p2 = doc.new_page(width=300, height=400)
    p2.insert_image(p2.rect, stream=buf_content.getvalue())

    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/pdf/remove-blank-pages",
        files={"file": ("scanned.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["x-original-pages"] == "2"
    assert response.headers["x-removed-pages"] == "1"
    assert response.headers["x-remaining-pages"] == "1"
    assert json.loads(response.headers["x-removed-page-numbers"]) == [1]

    cleaned_doc = fitz.open(stream=response.content, filetype="pdf")
    assert cleaned_doc.page_count == 1
    cleaned_doc.close()


def test_remove_blank_pages_empty_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    response = client.post(
        "/api/v1/pdf/remove-blank-pages",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_remove_blank_pages_non_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    response = client.post(
        "/api/v1/pdf/remove-blank-pages",
        files={"file": ("notes.txt", b"Hello text", "text/plain")},
    )
    assert response.status_code == 415


def test_repair_pdf_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    # Create a valid PDF then corrupt its xref
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((50, 50), "Important Document")
    valid_bytes = doc.tobytes()
    doc.close()

    corrupted_bytes = valid_bytes.replace(b"xref", b"xxxx", 1)

    response = client.post(
        "/api/v1/pdf/repair",
        files={"file": ("damaged.pdf", corrupted_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-pdf-repaired"] == "true"
    assert response.headers["x-pdf-pages"] == "1"

    repaired_doc = fitz.open(stream=response.content, filetype="pdf")
    assert repaired_doc.page_count == 1
    assert "Important Document" in repaired_doc[0].get_text()
    repaired_doc.close()

