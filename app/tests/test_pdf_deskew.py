from types import SimpleNamespace

import numpy as np
import pytest
import pymupdf
from PIL import Image
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.pdf_processing import deskew
from app.services.pdf_processing import deskew_service

client = TestClient(app)


@pytest.mark.parametrize(
    "lines",
    [
        np.array([[100, 10, 200, 20], [100, 30, 200, 40], [100, 50, 200, 60]]),
        np.array([[[100, 10, 200, 20]], [[100, 30, 200, 40]], [[100, 50, 200, 60]]]),
    ],
)
def test_detect_skew_accepts_hough_segments_with_or_without_singleton_axis(monkeypatch, lines):
    cv2_stub = SimpleNamespace(
        THRESH_BINARY_INV=1,
        THRESH_OTSU=2,
        threshold=lambda arr, *_args: (None, arr),
        Canny=lambda *_args, **_kwargs: np.zeros((100, 100), dtype=np.uint8),
        HoughLinesP=lambda *_args, **_kwargs: lines,
    )
    monkeypatch.setattr(deskew, "cv2", cv2_stub)
    monkeypatch.setattr(deskew, "_HAS_CV2", True)

    angle, confidence = deskew.detect_skew(Image.new("L", (100, 100)))

    assert angle == pytest.approx(np.degrees(np.arctan2(10, 100)))
    assert confidence == pytest.approx(1.0)


def test_manual_deskew_angle_bypasses_detection_and_is_applied(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    destination = tmp_path / "deskewed.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(source)
    document.close()

    rotations = []
    monkeypatch.setattr(
        deskew_service,
        "render_page_to_image",
        lambda *_args, **_kwargs: Image.new("RGB", (100, 100), "white"),
    )
    monkeypatch.setattr(
        deskew_service,
        "detect_skew",
        lambda *_args, **_kwargs: pytest.fail("manual mode must not auto-detect skew"),
    )
    monkeypatch.setattr(
        deskew_service,
        "deskew_image",
        lambda image, angle: rotations.append(angle) or image,
    )

    result = deskew_service.deskew_pdf(source, destination, manual_angle=2.5)

    assert rotations == [2.5]
    assert result == {"pages_total": 1, "pages_corrected": 1}
    assert destination.is_file()


def test_manual_deskew_angles_are_applied_to_their_pages(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    destination = tmp_path / "deskewed.pdf"
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    document.save(source)
    document.close()

    rotations = []
    monkeypatch.setattr(
        deskew_service,
        "render_page_to_image",
        lambda *_args, **_kwargs: Image.new("RGB", (100, 100), "white"),
    )
    monkeypatch.setattr(
        deskew_service,
        "detect_skew",
        lambda *_args, **_kwargs: pytest.fail("manual mode must not auto-detect skew"),
    )
    monkeypatch.setattr(
        deskew_service,
        "deskew_image",
        lambda image, angle: rotations.append(angle) or image,
    )

    result = deskew_service.deskew_pdf(
        source,
        destination,
        manual_angles=[2.5, -1.2],
    )

    assert rotations == [2.5, -1.2]
    assert result == {"pages_total": 2, "pages_corrected": 2}
    assert destination.is_file()


def test_deskew_endpoint_accepts_manual_angle(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    received_angles = []

    def fake_deskew_pdf(source, destination, *, manual_angle=None, manual_angles=None):
        assert source.is_file()
        received_angles.append(manual_angle)
        document = pymupdf.open()
        document.new_page()
        document.save(destination)
        document.close()

    monkeypatch.setattr("app.routers.pdf_deskew.deskew_pdf", fake_deskew_pdf)
    document = pymupdf.open()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/deskew",
        params={"manual_angle": "-3.2"},
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert received_angles == [-3.2]


def test_deskew_endpoint_rejects_wrong_number_of_page_angles(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    document = pymupdf.open()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/deskew",
        data={"manual_angles": "[1.0, 2.0]"},
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 422
    assert "exactly 1 page values" in response.json()["detail"]


def test_deskew_endpoint_accepts_separate_angles_per_page(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    received_angles = []

    def fake_deskew_pdf(source, destination, *, manual_angle=None, manual_angles=None):
        assert source.is_file()
        received_angles.append(manual_angles)
        document = pymupdf.open()
        document.new_page()
        document.new_page()
        document.save(destination)
        document.close()

    monkeypatch.setattr("app.routers.pdf_deskew.deskew_pdf", fake_deskew_pdf)
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/deskew",
        data={"manual_angles": "[1.5, -2.0]"},
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert received_angles == [[1.5, -2.0]]


def test_deskew_preview_returns_all_page_thumbnails(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/api/v1/pdf/deskew/preview",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    pages = response.json()["pages"]
    assert [page["page"] for page in pages] == [1, 2]
    assert all(page["preview"] for page in pages)
