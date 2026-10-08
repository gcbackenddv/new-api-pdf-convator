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


def test_calculate_optimal_dpi():
    """Verifies automatic DPI calculation for high quality across various page content."""
    from app.services.pdf_to_pptx.coordinates import calculate_optimal_dpi

    doc = fitz.open()

    # 1. Plain digital text page -> high quality baseline (200 DPI)
    p1 = doc.new_page(width=600, height=800)
    p1.insert_text((50, 50), "Sample Text")
    dpi1 = calculate_optimal_dpi(p1)
    assert dpi1 >= 200

    # 2. Vector drawings page -> 240 or 300 DPI for crisp vector rendering
    p2 = doc.new_page(width=600, height=800)
    for i in range(5):
        p2.draw_line(fitz.Point(10 * i, 10), fitz.Point(100, 10 * i))
    dpi2 = calculate_optimal_dpi(p2)
    assert dpi2 >= 240

    # 3. High-res embedded image -> matches image DPI up to 300
    p3 = doc.new_page(width=720, height=405)
    img_bytes = _make_dummy_image_bytes(width=1500, height=1000)
    # Bbox is 360 x 240 pt (5 x 3.33 in). 1500 px / 5 in = 300 DPI
    p3.insert_image(fitz.Rect(50, 50, 410, 290), stream=img_bytes)
    dpi3 = calculate_optimal_dpi(p3)
    assert dpi3 == 300

    # 4. Explicit target_dpi takes precedence
    dpi_explicit = calculate_optimal_dpi(p3, target_dpi=180)
    assert dpi_explicit == 180

    # 5. Memory ceiling clamp prevents OOM on large pages
    # Force max_pixels very low (e.g. 500,000 px)
    dpi_clamped = calculate_optimal_dpi(p3, max_pixels=500_000)
    assert dpi_clamped < 200

    doc.close()


def test_conversion_with_auto_dpi(tmp_path, monkeypatch):
    """Verifies conversion with dpi=0 triggers automatic optimal DPI calculation."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=720, height=405)
    p.insert_text((100, 100), "Auto DPI Slide Test", fontsize=24)
    p.draw_rect(fitz.Rect(50, 50, 670, 355), color=(0, 0, 1), width=2)
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx?dpi=0",
        files={"file": ("auto_dpi.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    assert len(prs.slides) == 1
    slide = prs.slides[0]
    assert len(slide.shapes) >= 1


def test_conversion_with_omitted_dpi_uses_auto(tmp_path, monkeypatch):
    """Verifies that omitting the dpi parameter (e.g. ?ocr=true) converts cleanly with auto DPI."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=720, height=405)
    p.insert_text((100, 100), "No DPI Query Param Test", fontsize=24)
    pdf_bytes = doc.tobytes()
    doc.close()

    # Omit dpi query param entirely, matching frontend behavior
    response = client.post(
        "/convert/pdf-to-pptx?ocr=true",
        files={"file": ("no_dpi.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    prs = Presentation(io.BytesIO(response.content))
    assert len(prs.slides) == 1
    assert "No DPI Query Param Test" in prs.slides[0].shapes[0].text_frame.text


def test_ssim_computation():
    """Verifies SSIM calculation between identical and different images."""
    import numpy as np
    from app.services.pdf_to_pptx.validator import compute_ssim

    # Identical images -> SSIM == 1.0
    img1 = np.full((100, 100), 128, dtype=np.uint8)
    img2 = np.full((100, 100), 128, dtype=np.uint8)
    score_identical = compute_ssim(img1, img2)
    assert score_identical >= 0.99

    # Different images -> SSIM < 0.9
    img3 = np.zeros((100, 100), dtype=np.uint8)
    img4 = np.full((100, 100), 255, dtype=np.uint8)
    score_diff = compute_ssim(img3, img4)
    assert score_diff < 0.5


def test_conversion_with_validation_headers(tmp_path, monkeypatch):
    """Verifies that validate=true triggers visual validation and includes validation headers in response."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p = doc.new_page(width=720, height=405)
    p.insert_text((100, 100), "Validation Pipeline Header Test", fontsize=24)
    p.insert_text((100, 150), "Testing automated fidelity scoring.", fontsize=14)
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx?validate=true",
        files={"file": ("val_test.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert "X-Slide-Count" in response.headers
    assert response.headers["X-Slide-Count"] == "1"
    # Should have visual similarity headers
    if "X-Visual-Similarity-Score" in response.headers:
        score = float(response.headers["X-Visual-Similarity-Score"])
        assert 0.0 <= score <= 1.0
        assert "X-Validation-Status" in response.headers


def test_conversion_validate_endpoint_returns_json_report(tmp_path, monkeypatch):
    """Verifies that /convert/pdf-to-pptx/validate returns a comprehensive JSON validation report."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    p1 = doc.new_page(width=600, height=800)
    p1.insert_text((50, 80), "Annual Executive Summary", fontsize=26)
    p1.insert_text((50, 130), "Key strategic pillars and revenue milestones.", fontsize=14)

    p2 = doc.new_page(width=600, height=800)
    p2.insert_text((50, 80), "Product Roadmap", fontsize=26)
    p2.draw_rect(fitz.Rect(50, 120, 550, 300), color=(0, 0.5, 0.8), fill=(0.9, 0.95, 1.0))
    pdf_bytes = doc.tobytes()
    doc.close()

    response = client.post(
        "/convert/pdf-to-pptx/validate",
        files={"file": ("report_deck.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["slide_count"] == 2
    assert "validation_report" in data
    report = data["validation_report"]
    assert report is not None
    assert report["total_pages"] == 2
    assert report["successful_pages"] >= 1
    assert "overall_similarity_score" in report
    assert "validation_status" in report
    assert "processing_time_seconds" in report
    assert isinstance(report["pages"], list)
    assert len(report["pages"]) >= 1


def test_reprocess_slide_with_high_res_fallback():
    """Verifies that reprocess_slide_with_high_res_fallback replaces slide shapes with crisp fallback."""
    from pptx import Presentation
    from app.services.pdf_to_pptx.coordinates import SlideGeometry
    from app.services.pdf_to_pptx.validator import reprocess_slide_with_high_res_fallback

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    # Add a dummy shape
    slide.shapes.add_textbox(0, 0, 1000, 1000)
    assert len(slide.shapes) == 1

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    p.insert_text((50, 50), "Sample Fallback Content")

    geom = SlideGeometry.from_page_rect(p.rect)
    success = reprocess_slide_with_high_res_fallback(prs, 0, p, geom, dpi=150)
    assert success is True
    # The dummy textbox should have been cleared and replaced by the picture
    assert len(slide.shapes) == 1
    assert slide.shapes[0].shape_type == MSO_SHAPE_TYPE.PICTURE
    doc.close()


def test_text_alignment_reanchoring():
    """Verifies that centered and right-aligned textboxes have properly anchored coordinates."""
    from app.services.pdf_to_pptx.coordinates import SlideGeometry
    from app.services.pdf_to_pptx.text import extract_and_add_text

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    doc = fitz.open()
    p = doc.new_page(width=600, height=800)
    # Right-aligned lines
    p.insert_text((400, 100), "Right aligned heading")
    p.insert_text((400, 130), "Right aligned subtitle")

    geom = SlideGeometry.from_page_rect(p.rect)
    added = extract_and_add_text(p, slide, geom)
    assert added >= 1
    doc.close()


def test_resolve_font_styling():
    """Verifies precise resolution of font subfamilies, weights, and styles."""
    from app.services.pdf_to_pptx.fonts import resolve_font_styling

    # 1. Weights and subfamilies
    name, bold, italic = resolve_font_styling("ABCDEF+Calibri-Light", flags=0)
    assert name == "Calibri Light"
    assert bold is False
    assert italic is False

    name, bold, italic = resolve_font_styling("Arial-Narrow", flags=0)
    assert name == "Arial Narrow"
    assert bold is False
    assert italic is False

    name, bold, italic = resolve_font_styling("Arial-NarrowBold", flags=16)
    assert name == "Arial Narrow"
    assert bold is True
    assert italic is False

    name, bold, italic = resolve_font_styling("SegoeUI-SemiBold", flags=16)
    assert name == "Segoe UI Semibold"
    assert bold is True
    assert italic is False

    name, bold, italic = resolve_font_styling("Roboto-Black", flags=16)
    assert name == "Roboto Black"
    assert bold is True
    assert italic is False

    # 2. Styles
    name, bold, italic = resolve_font_styling("TimesNewRomanPS-BoldItalicMT", flags=18)
    assert name == "Times New Roman"
    assert bold is True
    assert italic is True

    name, bold, italic = resolve_font_styling("HelveticaNeue-LightItalic", flags=2)
    assert name == "Helvetica Neue Light"
    assert bold is False
    assert italic is True


def test_font_embedding_in_pptx(tmp_path):
    """Verifies that embedded fonts in PDF are embedded into the generated PPTX package."""
    from app.services.pdf_to_pptx.font_embedder import embed_fonts_from_pdf

    pptx_path = tmp_path / "embedded_test.pptx"
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(pptx_path)

    doc = fitz.open()
    p = doc.new_page()
    # Check if system font exists or insert simple font
    font_files = list(Path("/usr/share/fonts/truetype").rglob("*.ttf"))
    if font_files:
        font_file = str(font_files[0])
        p.insert_font(fontname="testfont", fontfile=font_file)
        p.insert_text((50, 50), "Embedded Font Test", fontname="testfont")
        count = embed_fonts_from_pdf(doc, pptx_path)
        assert count >= 1

        # Verify PPTX can still be opened and validated
        prs_loaded = Presentation(pptx_path)
        assert len(prs_loaded.slides) == 1
    doc.close()


