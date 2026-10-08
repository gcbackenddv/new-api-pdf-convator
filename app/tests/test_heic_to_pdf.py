import io

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pillow_heif import register_heif_opener

from app.config import settings
from app.main import app

register_heif_opener()
client = TestClient(app)
URL = "/convert/heic-to-pdf"


def make_heic(w=300, h=400, color=(200, 30, 30), mode="RGB", orientation=None) -> bytes:
    img = Image.new(mode, (w, h), color)
    buf = io.BytesIO()
    if orientation:
        import pillow_heif
        heif_file = pillow_heif.from_pillow(img)
        exif = Image.Exif()
        exif[0x0112] = orientation
        heif_file.info["exif"] = exif.tobytes()
        heif_file.save(buf, quality=90)
    else:
        img.save(buf, format="HEIF", quality=90)
    return buf.getvalue()


def post(items, **params):
    files = [("files", (name, data, "image/heic")) for name, data in items]
    return client.post(URL, files=files, params=params)


def pages(content: bytes) -> list[fitz.Rect]:
    with fitz.open(stream=content, filetype="pdf") as doc:
        return [p.rect for p in doc]


def test_single_image():
    r = post([("a.heic", make_heic())], dpi=72)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "a_converted.pdf" in r.headers["content-disposition"]
    rects = pages(r.content)
    assert len(rects) == 1
    assert (round(rects[0].width), round(rects[0].height)) == (300, 400)


def test_multiple_images_keep_order():
    items = [("1.heic", make_heic(300, 400)), ("2.heic", make_heic(500, 200)), ("3.heic", make_heic(100, 100))]
    response = post(items, dpi=72)
    assert "converted_images_converted.pdf" in response.headers["content-disposition"]
    rects = pages(response.content)
    assert [(round(r.width), round(r.height)) for r in rects] == [(300, 400), (500, 200), (100, 100)]


def test_dpi_scales_page_size():
    rects = pages(post([("a.heic", make_heic(300, 400))], dpi=144).content)
    assert (round(rects[0].width), round(rects[0].height)) == (150, 200)


def test_a4_page_size():
    rects = pages(post([("p.heic", make_heic(300, 400)), ("l.heic", make_heic(400, 300))], page_size="a4").content)
    assert (round(rects[0].width), round(rects[0].height)) == (595, 842)
    assert (round(rects[1].width), round(rects[1].height)) == (842, 595)


def test_exif_orientation_applied():
    rects = pages(post([("a.heic", make_heic(300, 400, orientation=6))], dpi=72).content)
    assert (round(rects[0].width), round(rects[0].height)) == (400, 300)


def test_alpha_image():
    r = post([("a.heic", make_heic(mode="RGBA", color=(255, 0, 0, 128)))], dpi=72)
    assert r.status_code == 200


def test_wrong_extension():
    assert post([("a.txt", make_heic())]).status_code == 400


def test_not_really_heic():
    assert post([("a.heic", b"this is not an image at all")]).status_code == 400


def test_empty_file():
    assert post([("a.heic", b"")]).status_code == 400


def test_corrupted_heic():
    assert post([("a.heic", make_heic()[:60])]).status_code in (400, 422)


def test_missing_upload():
    assert client.post(URL).status_code == 422


def test_too_many_files(monkeypatch):
    monkeypatch.setattr(settings, "HEIC_PDF_MAX_FILES", 2)
    items = [(f"{i}.heic", make_heic(50, 50)) for i in range(3)]
    assert post(items).status_code == 413


def test_image_too_large(monkeypatch):
    monkeypatch.setattr(settings, "HEIC_PDF_MAX_PIXELS", 1000)
    assert post([("a.heic", make_heic(300, 400))]).status_code == 413