from fastapi.testclient import TestClient
import pymupdf

from app.config import settings
from app.main import app

client = TestClient(app)


def test_extract_tables_endpoint_returns_json_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    document = pymupdf.open()
    page = document.new_page()
    shape = page.new_shape()
    for x in (72, 220, 368):
        shape.draw_line((x, 100), (x, 180))
    for y in (100, 140, 180):
        shape.draw_line((72, y), (368, y))
    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()
    page.insert_text((80, 125), "Item")
    page.insert_text((230, 125), "Price")
    page.insert_text((80, 165), "Tea")
    page.insert_text((230, 165), "5")
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/extract-tables",
        params={"output_format": "json", "ocr": "false"},
        files={"file": ("table.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-table-count"] == "1"
    table = response.json()["tables"][0]
    assert table["columns"] == ["Item", "Price"]
    assert table["rows"] == [{"Item": "Tea", "Price": "5"}]
