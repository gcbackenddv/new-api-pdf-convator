from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import pdf_to_heic as pdf_to_heic_router

client = TestClient(app)


def test_output_uses_uploaded_name_and_is_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    def fake_convert(_pdf_path, work_dir, **_kwargs):
        zip_path = work_dir / "converted.zip"
        zip_path.write_bytes(b"zip-data")
        return SimpleNamespace(zip_path=zip_path)

    monkeypatch.setattr(pdf_to_heic_router, "convert_pdf_to_heic_zip", fake_convert)
    response = client.post(
        "/convert/pdf-to-heic",
        files={"file": ("../presentation.pdf", b"pdf-data", "application/pdf")},
    )

    assert response.status_code == 200
    assert "presentation_converted.zip" in response.headers["content-disposition"]
    saved_files = list(tmp_path.glob("presentation_converted-*.zip"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"zip-data"
