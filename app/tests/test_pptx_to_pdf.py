from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.pptx_to_pdf import find_soffice

client = TestClient(app)


def test_find_soffice_configured(tmp_path):
    fake_soffice = tmp_path / "fake_soffice"
    fake_soffice.write_text("dummy binary")
    assert find_soffice(str(fake_soffice)) == fake_soffice


def test_find_soffice_configured_dir(tmp_path):
    fake_bin = tmp_path / "soffice"
    fake_bin.write_text("dummy binary")
    assert find_soffice(str(tmp_path)) == fake_bin


def test_health_check_missing_soffice():
    with patch("app.routers.pptx_to_pdf.find_soffice", return_value=None):
        response = client.get("/convert/pptx-to-pdf/health")
        assert response.status_code == 503
        assert "LibreOffice" in response.json()["detail"]


def test_health_check_found_soffice():
    dummy_path = Path("/mock/soffice")
    with patch("app.routers.pptx_to_pdf.find_soffice", return_value=dummy_path):
        response = client.get("/convert/pptx-to-pdf/health")
        assert response.status_code == 200
        assert response.json() == {"available": True, "soffice_path": str(dummy_path)}


def test_pptx_to_pdf_missing_engine():
    with patch("app.services.pptx_to_pdf.find_soffice", return_value=None):
        response = client.post(
            "/convert/pptx-to-pdf",
            files={"file": ("test.pptx", b"dummy content", "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
        assert response.status_code in (400, 503)


def test_pptx_to_pdf_invalid_extension():
    response = client.post(
        "/convert/pptx-to-pdf",
        files={"file": ("test.txt", b"some text", "text/plain")},
    )
    assert response.status_code == 400
    assert "Only .ppt and .pptx" in response.json()["detail"]


def test_pptx_to_pdf_empty_file():
    response = client.post(
        "/convert/pptx-to-pdf",
        files={"file": ("test.pptx", b"", "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_favicon_route():
    response = client.get("/favicon.ico")
    assert response.status_code == 204
