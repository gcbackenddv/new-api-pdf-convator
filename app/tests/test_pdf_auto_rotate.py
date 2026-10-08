from fastapi.testclient import TestClient
import fitz

from app.main import app

client = TestClient(app)


def test_auto_rotate_pdf_endpoint():
    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    p.insert_text((100, 100), "Hello orientation test")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/pdf/auto-rotate",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert len(response.content) > 0


def test_auto_rotate_empty_file():
    response = client.post(
        "/api/v1/pdf/auto-rotate",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_auto_rotate_invalid_pdf():
    response = client.post(
        "/api/v1/pdf/auto-rotate",
        files={"file": ("fake.pdf", b"not-a-pdf", "application/pdf")},
    )
    assert response.status_code == 400

