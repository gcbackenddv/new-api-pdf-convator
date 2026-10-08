"""Focused tests for the PDF Repair endpoint (/repair-pdf and /api/v1/pdf/repair)."""
import io
import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def _make_sample_pdf(text: str = "Healthy PDF Document") -> bytes:
    doc = fitz.open()
    p = doc.new_page(width=300, height=400)
    p.insert_text((50, 50), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_repair_pdf_valid_document(tmp_path, monkeypatch):
    """A valid PDF passes through, is cleaned/sanitized, and returns valid PDF download."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    pdf_bytes = _make_sample_pdf("Valid Test Document")

    response = client.post(
        "/repair-pdf",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="repaired_sample.pdf"' in response.headers["content-disposition"]
    assert response.headers["x-pdf-pages"] == "1"

    doc = fitz.open(stream=response.content, filetype="pdf")
    assert doc.page_count == 1
    assert "Valid Test Document" in doc[0].get_text()
    doc.close()


def test_repair_pdf_corrupted_xref(tmp_path, monkeypatch):
    """A PDF with broken XREF table and damaged startxref offset pointer is successfully repaired."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    clean_bytes = _make_sample_pdf("Invoice #98234")

    # Corrupt both xref keyword and startxref offset
    corrupted_bytes = clean_bytes.replace(b"xref", b"xxxx", 1)
    corrupted_bytes = corrupted_bytes.replace(b"startxref", b"startxref\n9999999\n%")

    response = client.post(
        "/repair-pdf",
        files={"file": ("broken_invoice.pdf", corrupted_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-pdf-repaired"] == "true"
    assert 'filename="repaired_broken_invoice.pdf"' in response.headers["content-disposition"]

    doc = fitz.open(stream=response.content, filetype="pdf")
    assert doc.page_count == 1
    assert "Invoice #98234" in doc[0].get_text()
    doc.close()


def test_repair_pdf_truncated_eof(tmp_path, monkeypatch):
    """A PDF with missing %%EOF marker (truncated download) is recovered."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    clean_bytes = _make_sample_pdf("Recoverable Stream")

    eof_idx = clean_bytes.rfind(b"%%EOF")
    truncated_bytes = clean_bytes[:eof_idx]

    response = client.post(
        "/repair-pdf",
        files={"file": ("truncated.pdf", truncated_bytes, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"

    doc = fitz.open(stream=response.content, filetype="pdf")
    assert doc.page_count == 1
    assert "Recoverable Stream" in doc[0].get_text()
    doc.close()


def test_repair_pdf_invalid_file_extension(tmp_path, monkeypatch):
    """Non-pdf extension is rejected with 400."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    response = client.post(
        "/repair-pdf",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
    )

    assert response.status_code == 400
    assert "Please upload a .pdf file." in response.json()["detail"]


def test_repair_pdf_empty_file(tmp_path, monkeypatch):
    """Empty 0-byte file is rejected with 400."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    response = client.post(
        "/repair-pdf",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert "The uploaded file is empty." in response.json()["detail"]


def test_repair_pdf_non_pdf_content(tmp_path, monkeypatch):
    """Binary garbage with .pdf filename is rejected with 400."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    garbage = b"This is not a PDF file at all, just arbitrary text characters."
    response = client.post(
        "/repair-pdf",
        files={"file": ("fake.pdf", garbage, "application/pdf")},
    )

    assert response.status_code == 400
    assert "not a PDF document" in response.json()["detail"]


def test_repair_pdf_encrypted_file(tmp_path, monkeypatch):
    """Password-protected / encrypted PDF cannot be repaired without password and returns 400."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    doc = fitz.open()
    doc.new_page()
    enc_path = tmp_path / "enc.pdf"
    doc.save(enc_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret123")
    doc.close()

    enc_bytes = enc_path.read_bytes()
    response = client.post(
        "/repair-pdf",
        files={"file": ("locked.pdf", enc_bytes, "application/pdf")},
    )

    assert response.status_code == 400
    assert "Encrypted" in response.json()["detail"]


def test_repair_pdf_unrecoverable_corrupted_file(tmp_path, monkeypatch):
    """A completely ruined file that has %PDF- signature but destroyed stream data returns 400."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)

    # %PDF- header followed by non-recoverable bytes
    ruined_bytes = b"%PDF-1.4\n" + b"\x00\xff\xee\xdd\xcc\xbb\xaa\x99" * 40
    response = client.post(
        "/repair-pdf",
        files={"file": ("ruined.pdf", ruined_bytes, "application/pdf")},
    )

    assert response.status_code == 400
    assert "could not be repaired" in response.json()["detail"]


def test_repair_pdf_exceeds_max_size(tmp_path, monkeypatch):
    """File exceeding MAX_PDF_SIZE_MB is rejected with 413."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(settings, "MAX_PDF_SIZE_MB", 1)

    big_content = b"%PDF-1.4\n" + (b"0" * (1024 * 1024 + 100))
    response = client.post(
        "/repair-pdf",
        files={"file": ("big.pdf", big_content, "application/pdf")},
    )

    assert response.status_code == 413
    assert "exceeds maximum allowed size" in response.json()["detail"]


def test_repair_pdf_alias_endpoint(tmp_path, monkeypatch):
    """Verify /api/v1/pdf/repair alias route functions identically."""
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    pdf_bytes = _make_sample_pdf("Alias Route Check")

    response = client.post(
        "/api/v1/pdf/repair",
        files={"file": ("document.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="repaired_document.pdf"' in response.headers["content-disposition"]

