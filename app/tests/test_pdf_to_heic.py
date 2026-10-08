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


def test_pdf_to_heic_real_conversion(tmp_path, monkeypatch):
    import io
    import zipfile
    import pymupdf as fitz

    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    # Generate multi-page PDF in memory
    doc = fitz.open()
    for i in range(3):
        p = doc.new_page(width=300, height=400)
        p.insert_text((30, 50), f"Test Page {i + 1}", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-heic",
        params={"dpi": 72, "quality": 75},
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "sample_converted.zip" in response.headers["content-disposition"]

    # Verify zip content
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        namelist = zf.namelist()
        assert len(namelist) == 3
        assert "page-001.heic" in namelist
        assert "page-002.heic" in namelist
        assert "page-003.heic" in namelist
        # Verify non-empty HEIC data
        assert len(zf.read("page-001.heic")) > 100

