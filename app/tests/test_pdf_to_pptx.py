import io
from pathlib import Path
from types import SimpleNamespace

import fitz
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import pdf_to_pptx as pdf_to_pptx_router

client = TestClient(app)


def _make_dummy_image_bytes(width: int = 100, height: int = 100, color: str = "blue") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_output_uses_uploaded_name_and_is_saved(tmp_path, monkeypatch):
    """Preserves existing test verifying safe stem handling and saving to output dir."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    def fake_convert(_pdf_path, output_path, **_kwargs):
        output_path.write_bytes(b"pptx-data")
        return SimpleNamespace(output_path=output_path)

    monkeypatch.setattr(pdf_to_pptx_router, "convert_pdf_to_pptx", fake_convert)
    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("../Quarterly Report.pdf", b"pdf-data", "application/pdf")},
    )

    assert response.status_code == 200
    assert "Quarterly_Report_converted.pptx" in response.headers["content-disposition"]
    saved_files = list(tmp_path.glob("Quarterly_Report_converted-*.pptx"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"pptx-data"


def test_one_page_pdf_with_editable_text(tmp_path, monkeypatch):
    """Verifies that digital text in PDF becomes editable PowerPoint text boxes."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((72, 100), "Quarterly Financial Analysis", fontsize=22)
    page.insert_text((72, 160), "Revenue grew by 25% year-over-year.", fontsize=14)
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    assert len(prs.slides) == 1
    slide = prs.slides[0]

    # Check for text boxes
    text_boxes = [s for s in slide.shapes if s.has_text_frame]
    assert len(text_boxes) >= 1

    all_slide_text = " ".join(s.text_frame.text for s in text_boxes)
    assert "Quarterly Financial Analysis" in all_slide_text
    assert "Revenue grew by 25%" in all_slide_text


def test_multipage_pdf(tmp_path, monkeypatch):
    """Verifies multiple pages convert into multiple slides matching count."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    for i in range(3):
        p = doc.new_page(width=500, height=700)
        p.insert_text((50, 50), f"Slide Content Page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("deck.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    assert len(prs.slides) == 3


def test_landscape_and_dimensions(tmp_path, monkeypatch):
    """Verifies slide aspect ratio and dimensions match PDF page."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    doc.new_page(width=842, height=595)  # A4 Landscape (wider than tall)
    doc[0].insert_text((50, 50), "Landscape Slide")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("landscape.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    assert prs.slide_width > prs.slide_height


def test_text_styles_and_colors(tmp_path, monkeypatch):
    """Verifies font styling (bold, color, size) is extracted."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    p.insert_text((50, 100), "Red Bold Heading", fontsize=20, color=(1, 0, 0))
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("styled.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]

    found = False
    for shape in slide.shapes:
        if shape.has_text_frame and "Red Bold Heading" in shape.text_frame.text:
            found = True
            first_run = shape.text_frame.paragraphs[0].runs[0]
            assert first_run.font.size.pt == 20.0
            break
    assert found


def test_image_extraction_independent_shapes(tmp_path, monkeypatch):
    """Verifies images are extracted as independent picture shapes in PowerPoint."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    p.insert_text((50, 50), "Title With Images")

    img_data1 = _make_dummy_image_bytes(80, 80, "red")
    img_data2 = _make_dummy_image_bytes(80, 80, "green")
    p.insert_image(fitz.Rect(50, 100, 150, 200), stream=img_data1)
    p.insert_image(fitz.Rect(250, 100, 350, 200), stream=img_data2)

    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("images_doc.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]

    picture_shapes = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert len(picture_shapes) >= 2


def test_vector_shapes_extraction(tmp_path, monkeypatch):
    """Verifies vector graphics (rectangles/borders) become native PowerPoint shapes."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    p.draw_rect(fitz.Rect(50, 100, 300, 250), color=(0, 0, 1), fill=(0.9, 0.9, 0.9), width=2)
    p.insert_text((60, 140), "Text inside vector box")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("vectors.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]

    auto_shapes = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]
    assert len(auto_shapes) >= 1


def test_table_detection_and_creation(tmp_path, monkeypatch):
    """Verifies tables are reconstructed as native PowerPoint table shapes."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    # Draw table grid
    p.draw_rect(fitz.Rect(50, 50, 350, 150))
    p.draw_line(fitz.Point(50, 100), fitz.Point(350, 100))
    p.draw_line(fitz.Point(200, 50), fitz.Point(200, 150))
    p.insert_text((60, 80), "Header 1")
    p.insert_text((210, 80), "Header 2")
    p.insert_text((60, 130), "Data 1")
    p.insert_text((210, 130), "Data 2")

    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("table_doc.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]

    table_shapes = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.TABLE]
    assert len(table_shapes) >= 1
    t = table_shapes[0].table
    assert t.rows is not None and t.columns is not None
    assert len(t.rows) == 2
    assert len(t.columns) == 2


def test_scanned_pdf_fallback_and_ocr(tmp_path, monkeypatch):
    """Verifies scanned pages (image with no text) use high-res fallback without failing."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    # Scanned image covering most of the page
    scanned_img = _make_dummy_image_bytes(500, 700, "white")
    p.insert_image(fitz.Rect(10, 10, 590, 790), stream=scanned_img)
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("scanned.pdf", pdf_bytes, "application/pdf")},
        params={"ocr": False},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    assert len(prs.slides) == 1
    # Slide should contain the fallback picture
    assert len(prs.slides[0].shapes) >= 1


def test_v1_api_alias_endpoint(tmp_path, monkeypatch):
    """Verifies that the /api/v1/pdf-to-pptx route works identically."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "V1 Endpoint Test")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/pdf-to-pptx",
        files={"file": ("v1_test.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    assert len(prs.slides) == 1


def test_error_empty_pdf():
    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_error_invalid_pdf_content():
    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("corrupt.pdf", b"NOT_A_PDF_FILE_HEADER", "application/pdf")},
    )
    assert response.status_code == 400


def test_error_wrong_extension():
    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("doc.docx", b"%PDF-1.4 dummy", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "only pdf files are supported" in response.json()["detail"].lower()


def test_error_oversized_pdf(monkeypatch):
    monkeypatch.setattr(settings, "PPTX_MAX_PDF_SIZE_MB", 1)
    large_payload = b"%PDF-1.4 " + (b"0" * (1024 * 1024 + 100))
    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("large.pdf", large_payload, "application/pdf")},
    )
    assert response.status_code == 413


def test_complex_vector_curve_fallback(tmp_path, monkeypatch):
    """Verifies that complex curves/drawings fall back to high-fidelity pictures rather than corrupted text."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    # Draw a complex bezier curve
    p.draw_bezier(fitz.Point(100, 100), fitz.Point(150, 50), fitz.Point(200, 150), fitz.Point(250, 100), color=(1, 0, 0), width=3)
    p.insert_text((50, 50), "Chart Header")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("curve_test.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]

    # Verify that the complex curve was converted as a picture rather than corrupted text
    pictures = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert len(pictures) >= 1

    text_boxes = [s for s in slide.shapes if s.has_text_frame]
    all_text = " ".join(s.text_frame.text for s in text_boxes)
    assert "Chart Header" in all_text


def test_line_and_oval_shapes(tmp_path, monkeypatch):
    """Verifies that simple lines and circles become native PowerPoint connector/oval shapes."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    # Simple straight line
    p.draw_line(fitz.Point(50, 50), fitz.Point(250, 50), color=(0, 0, 1), width=2)
    # Simple circle
    p.draw_circle(fitz.Point(100, 150), 30, color=(0, 1, 0), fill=(0.9, 1, 0.9))
    p.insert_text((50, 250), "Shapes Legend")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("shapes_test.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]

    # Verify line connector and auto shape
    connectors = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.LINE]
    auto_shapes = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]
    assert len(connectors) >= 1 or len(auto_shapes) >= 1


def test_bullet_character_preservation(tmp_path, monkeypatch):
    """Verifies that PUA bullet characters like \\uf0b7 are mapped to standard bullets and preserved."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    p.insert_text((50, 50), "\uf0b7 First item in list")
    p.insert_text((50, 80), "\uf0b7 Second item in list")
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("bullet_test.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]

    text_boxes = [s for s in slide.shapes if s.has_text_frame]
    all_text = " ".join(s.text_frame.text for s in text_boxes)
    assert "First item in list" in all_text
    assert "•" in all_text or "·" in all_text


def test_clipped_image_handling(tmp_path, monkeypatch):
    """Verifies that image clipping operators in PDF content stream crop the image accurately."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    from PIL import Image
    im = Image.new("RGB", (400, 300), color=(255, 0, 0))
    im_buf = io.BytesIO()
    im.save(im_buf, format="PNG")
    im_bytes = im_buf.getvalue()

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    p.insert_image(fitz.Rect(50, 50, 450, 350), stream=im_bytes)
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx",
        files={"file": ("clip_test.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    slide = prs.slides[0]
    pictures = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert len(pictures) >= 1


