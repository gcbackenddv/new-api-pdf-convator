# File Conversion API

A FastAPI-based file conversion service supporting PDF, HEIC, Images, and PowerPoint formats.

## System Prerequisites

### Tesseract OCR (Required for searchable PDFs and scanned-document OCR)
Install Tesseract and the language data you request. The default OCR language is
`eng+ben`, so both English and Bengali trained data are required for the default.

- **Ubuntu / Debian**:
  ```bash
  sudo apt update
  sudo apt install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-ben fonts-noto-core
  ```
  Run these commands on the same host or inside the same container that runs
  Uvicorn, then verify the executable and language data:
  ```bash
  tesseract --version
  tesseract --list-langs
  ```
  The language list must include `eng` for requests using `lang=eng`. The
  default `OCR_LANGUAGE=eng+ben` requires both `eng` and `ben`. Restart the API
  process after installing Tesseract so it uses the updated server environment.

- **macOS**:
  ```bash
  brew install tesseract
  ```
  Install the requested `.traineddata` language files if they are not included
  by your Tesseract package.

- **Windows**: Install Tesseract OCR and make sure `tesseract.exe` is on `PATH`.
  Install the `.traineddata` files for the requested languages.

The `pytesseract` Python package alone does not install the Tesseract executable
or its language data. The searchable-PDF endpoint reports an error instead of
returning an unchanged PDF when OCR is unavailable or recognizes no text. For
languages needing a non-Latin font, install a compatible font or set
`OCR_FONT_PATH` to a TrueType font that contains the recognized script.

### LibreOffice (Required for PPT/PPTX -> PDF)
Converting PowerPoint files (`.ppt` and `.pptx`) to PDF uses LibreOffice in headless mode. LibreOffice must be installed on the host system:

- **Ubuntu / Debian**:
  ```bash
  sudo apt update
  sudo apt install -y libreoffice
  ```
  *(Or headless minimal: `sudo apt install -y --no-install-recommends libreoffice-impress libreoffice-core libreoffice-common`)*

- **macOS**:
  ```bash
  brew install --cask libreoffice
  ```

- **Windows**:
  Download and install from [libreoffice.org](https://www.libreoffice.org/).

If LibreOffice is installed in a custom location, specify its path in `.env`:
```env
PPTX_PDF_SOFFICE_PATH=/path/to/soffice
```

---

## Run Locally

1. Create and activate a virtual environment, then install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start the development server:

   **Linux / macOS**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   **Windows**:
   ```powershell
   .\venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

3. Open `http://127.0.0.1:8000/` to use the interactive conversion tester.
4. Interactive API documentation is available at `http://127.0.0.1:8000/docs`.
