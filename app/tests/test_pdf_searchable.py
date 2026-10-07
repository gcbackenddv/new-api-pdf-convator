from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.pdf_processing import searchable
from app.services.pdf_processing.ocr import OCRProcessingError

client = TestClient(app)


def _one_page_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def test_make_searchable_places_full_ocr_text_in_searchable_layer(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    destination = tmp_path / "searchable.pdf"
    source.write_bytes(_one_page_pdf())
    recognized_text = "searchable invoice number 12345 customer account details"

    monkeypatch.setattr(searchable, "ocr_available", lambda _language: True)
    monkeypatch.setattr(searchable, "ocr_image", lambda *_args, **_kwargs: recognized_text)

    result = searchable.make_searchable(source, destination, lang="eng", force_ocr=True)

    with pymupdf.open(destination) as output:
        extracted_text = output[0].get_text()

    assert "12345" in extracted_text
    assert "details" in extracted_text
    assert result["pages_ocrd"] == 1
    assert result["words_recognized"] == len(recognized_text.split())


def test_make_searchable_preserves_bengali_search_text(tmp_path, monkeypatch):
    font_path = "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf"
    if not Path(font_path).is_file():
        pytest.skip("Noto Sans Bengali font is not installed in this environment.")

    source = tmp_path / "source.pdf"
    destination = tmp_path / "searchable.pdf"
    source.write_bytes(_one_page_pdf())
    recognized_text = "বাংলা পরীক্ষা searchable invoice number details"

    monkeypatch.setattr(settings, "OCR_FONT_PATH", font_path)
    monkeypatch.setattr(searchable, "ocr_available", lambda _language: True)
    monkeypatch.setattr(searchable, "ocr_image", lambda *_args, **_kwargs: recognized_text)

    searchable.make_searchable(source, destination, lang="eng+ben", force_ocr=True)

    with pymupdf.open(destination) as output:
        extracted_text = output[0].get_text()

    assert "বাংলা" in extracted_text
    assert "পরীক্ষা" in extracted_text
    assert "searchable" in extracted_text


def test_force_ocr_does_not_return_success_when_recognition_is_empty(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    destination = tmp_path / "searchable.pdf"
    source.write_bytes(_one_page_pdf())

    monkeypatch.setattr(searchable, "ocr_available", lambda _language: True)
    monkeypatch.setattr(searchable, "ocr_image", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(searchable, "ocr_image_words", lambda *_args, **_kwargs: [])

    with pytest.raises(OCRProcessingError):
        searchable.make_searchable(source, destination, lang="eng", force_ocr=True)
    assert not destination.exists()


def test_text_pdf_does_not_require_tesseract_when_force_ocr_is_disabled(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    destination = tmp_path / "searchable.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 40), "This PDF already contains searchable text.")
    document.save(source)
    document.close()

    monkeypatch.setattr(searchable, "ocr_available", lambda _language: False)

    result = searchable.make_searchable(source, destination, lang="eng", force_ocr=False)

    assert result["pages_skipped"] == 1
    assert destination.is_file()


def test_make_searchable_endpoint_reports_missing_tesseract(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(searchable, "ocr_available", lambda _language: False)

    response = client.post(
        "/api/v1/pdf/make-searchable?lang=eng&force_ocr=true",
        files={"file": ("sample.pdf", _one_page_pdf(), "application/pdf")},
    )

    assert response.status_code == 503
    assert "Tesseract OCR or language data 'eng'" in response.json()["detail"]


def test_make_searchable_endpoint_reports_recognized_text_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    def create_searchable_pdf(_source, destination, **_options):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_one_page_pdf())
        return {"pages_total": 1, "pages_ocrd": 1, "pages_skipped": 0, "words_recognized": 37}

    monkeypatch.setattr("app.routers.pdf_searchable.make_searchable", create_searchable_pdf)

    response = client.post(
        "/api/v1/pdf/make-searchable?lang=eng&force_ocr=true",
        files={"file": ("sample.pdf", _one_page_pdf(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["x-ocr-pages"] == "1"
    assert response.headers["x-ocr-words"] == "37"


def test_make_searchable_auto_language_detection(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    destination = tmp_path / "searchable.pdf"
    source.write_bytes(_one_page_pdf())
    recognized_text = "automatic language detection test invoice"

    monkeypatch.setattr(searchable, "ocr_available", lambda _lang: True)
    monkeypatch.setattr("app.services.pdf_processing.ocr.get_installed_languages", lambda: ["eng", "ben"])
    monkeypatch.setattr(searchable, "ocr_image", lambda *_args, **_kwargs: recognized_text)

    result = searchable.make_searchable(source, destination, lang="auto", force_ocr=True)

    with pymupdf.open(destination) as output:
        extracted_text = output[0].get_text()

    assert "automatic" in extracted_text
    assert "invoice" in extracted_text
    assert result["pages_ocrd"] == 1

