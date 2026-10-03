import io

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

client = TestClient(app)
URL = "/convert/pdf-to-long-image"


def make_pdf(sizes: list[tuple[int, int]], black: set[int] | None = None) -> bytes:
    doc = fitz.open()
    for i, (w, h) in enumerate(sizes):
        page = doc.new_page(width=w, height=h)
        page.insert_text((20, 40), f"Page {i + 1}")
        if black and i in black:
            page.draw_rect(page.rect, fill=(0, 0, 0))
    data = doc.tobytes()
    doc.close()
    return data


def post(data: bytes, name="in.pdf", **params):
    return client.post(URL, files={"file": (name, data, "application/pdf")}, params=params)


def test_one_page():
    r = post(make_pdf([(595, 842)]), dpi=72)
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (595, 842)


def test_multi_page_height_is_sum():
    r = post(make_pdf([(595, 842)] * 4), dpi=72)
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (595, 842 * 4)


def test_mixed_sizes_and_centering():
    # A4 landscape, A4 portrait (black), Letter portrait
    r = post(make_pdf([(842, 595), (595, 842), (612, 792)], black={1}), dpi=72)
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    assert img.size == (842, 595 + 842 + 792)
    y = 595 + 400
    assert img.getpixel((50, y)) == (255, 255, 255)   # left margin of centered page
    assert img.getpixel((421, y)) == (0, 0, 0)        # page body
    assert img.getpixel((800, y)) == (255, 255, 255)  # right margin


@pytest.mark.parametrize(
    "fmt,pil_format,ext",
    [("png", "PNG", "png"), ("jpg", "JPEG", "jpg"), ("jpeg", "JPEG", "jpg"), ("heic", "HEIF", "heic")],
)
def test_output_formats(fmt, pil_format, ext):
    r = post(make_pdf([(595, 842)] * 2), format=fmt)
    assert r.status_code == 200
    assert f"in_converted.{ext}" in r.headers["content-disposition"]
    assert Image.open(io.BytesIO(r.content)).format == pil_format


def test_invalid_pdf():
    assert post(b"not a pdf at all").status_code == 400


def test_corrupted_pdf():
    assert post(make_pdf([(595, 842)] * 2)[:150]).status_code in (400, 422)


def test_unsupported_format():
    assert post(make_pdf([(595, 842)]), format="gif").status_code == 400


def test_empty_upload():
    assert post(b"").status_code == 400


def test_missing_upload():
    assert client.post(URL).status_code == 422  # FastAPI's own validation


def test_too_many_pages(monkeypatch):
    monkeypatch.setattr(settings, "LONG_IMAGE_MAX_PAGES", 5)
    assert post(make_pdf([(595, 842)] * 6), dpi=72).status_code == 413


def test_image_too_large(monkeypatch):
    monkeypatch.setattr(settings, "LONG_IMAGE_MAX_PIXELS", 1_000_000)
    assert post(make_pdf([(595, 842)] * 5), dpi=72).status_code == 413