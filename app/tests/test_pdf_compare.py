import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_compare_pdf_endpoint_returns_comparison_result(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Comparison test")
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/compare-pdf",
        files={
            "original_pdf": ("original.pdf", pdf_bytes, "application/pdf"),
            "new_pdf": ("new.pdf", pdf_bytes, "application/pdf"),
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["success"] is True
    assert result["pages_compared"] == 1
    assert result["reports"]["json"] == "compare-report.json"
    assert "json_content" in result["reports"]


def test_compare_pdf_endpoint_downloads_html_report(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Comparison test")
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/compare-pdf",
        params={"report_format": "html"},
        files={
            "original_pdf": ("original.pdf", pdf_bytes, "application/pdf"),
            "new_pdf": ("new.pdf", pdf_bytes, "application/pdf"),
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert 'filename="compare-report.html"' in response.headers["content-disposition"]
    assert "PDF Comparison Report" in response.text


def test_compare_pdf_endpoint_downloads_pdf_report(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Comparison test")
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/compare-pdf",
        params={"report_format": "pdf"},
        files={
            "original_pdf": ("original.pdf", pdf_bytes, "application/pdf"),
            "new_pdf": ("new.pdf", pdf_bytes, "application/pdf"),
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="compare-report.pdf"' in response.headers["content-disposition"]
    report = pymupdf.open(stream=response.content, filetype="pdf")
    assert "PDF Comparison Report" in report[0].get_text()
    report.close()
