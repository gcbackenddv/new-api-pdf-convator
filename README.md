# File Conversion API

A FastAPI-based file conversion service supporting PDF, HEIC, Images, and PowerPoint formats.

## System Prerequisites

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
