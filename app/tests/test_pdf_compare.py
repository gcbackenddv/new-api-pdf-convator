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


def test_compare_pdf_with_differences_and_visual_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    # Document 1 (Original)
    doc1 = pymupdf.open()
    p1 = doc1.new_page()
    p1.insert_text((72, 100), "Project Invoice #1001", fontsize=14)
    p1.insert_text((72, 140), "Total Amount: $500", fontsize=12)
    pdf1_bytes = doc1.tobytes()
    doc1.close()

    # Document 2 (Revised with modified price and added note)
    doc2 = pymupdf.open()
    p2 = doc2.new_page()
    p2.insert_text((72, 100), "Project Invoice #1001", fontsize=14)
    p2.insert_text((72, 140), "Total Amount: $750", fontsize=12)
    p2.insert_text((72, 180), "Payment Terms: Net 30 days", fontsize=11)
    pdf2_bytes = doc2.tobytes()
    doc2.close()

    # 1. JSON test: verifies bounding boxes and diff_image_data
    res_json = client.post(
        "/api/v1/compare-pdf",
        files={
            "original_pdf": ("doc1.pdf", pdf1_bytes, "application/pdf"),
            "new_pdf": ("doc2.pdf", pdf2_bytes, "application/pdf"),
        },
    )
    assert res_json.status_code == 200, res_json.text
    data = res_json.json()
    assert data["summary"]["total_differences"] > 0
    assert len(data["page_diffs"]) == 1

    page_diff = data["page_diffs"][0]
    assert page_diff["status"] == "modified"
    # Verify bounding boxes were computed
    modified_item = [d for d in page_diff["differences"] if d["change_type"] == "modified"][0]
    assert modified_item["bbox_old"] is not None
    assert modified_item["bbox_new"] is not None
    assert len(modified_item["bbox_old"]) == 4

    # 2. HTML report test: verifies professional styling & preview cards
    res_html = client.post(
        "/api/v1/compare-pdf",
        params={"report_format": "html"},
        files={
            "original_pdf": ("doc1.pdf", pdf1_bytes, "application/pdf"),
            "new_pdf": ("doc2.pdf", pdf2_bytes, "application/pdf"),
        },
    )
    assert res_html.status_code == 200, res_html.text
    html_text = res_html.text
    assert "PDF Comparison Report" in html_text
    assert "Page Structure &amp; Visual Analysis" in html_text or "Page Structure & Visual Analysis" in html_text
    assert "Detailed Difference Log" in html_text
    assert "Total Amount: $500" in html_text
    assert "Total Amount: $750" in html_text

    # 3. PDF report test: verifies multi-element PDF compilation
    res_pdf = client.post(
        "/api/v1/compare-pdf",
        params={"report_format": "pdf"},
        files={
            "original_pdf": ("doc1.pdf", pdf1_bytes, "application/pdf"),
            "new_pdf": ("doc2.pdf", pdf2_bytes, "application/pdf"),
        },
    )
    assert res_pdf.status_code == 200, res_pdf.text
    pdf_doc = pymupdf.open(stream=res_pdf.content, filetype="pdf")
    assert pdf_doc.page_count >= 1
    pdf_text = pdf_doc[0].get_text()
    assert "PDF Comparison Report" in pdf_text
    assert "DIFFERENCES FOUND" in pdf_text
    pdf_doc.close()

