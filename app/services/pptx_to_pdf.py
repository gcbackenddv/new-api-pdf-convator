import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF, used only to verify the output PDF

logger = logging.getLogger(__name__)

TEMP_PREFIX = "pptx2pdf_"
ALLOWED_EXTENSIONS = (".ppt", ".pptx")
_OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")  # legacy .ppt
_ZIP_MAGIC = b"PK\x03\x04"                      # .pptx
_SLIDE_RE = re.compile(r"ppt/slides/slide\d+\.xml")
_REL_TAG_RE = re.compile(rb"<Relationship\b[^>]*>", re.I)
_EXTERNAL_RE = re.compile(rb"""TargetMode\s*=\s*["']External["']""", re.I)
_TYPE_RE = re.compile(rb"""Type\s*=\s*["']([^"']+)["']""", re.I)
_MAX_RELS_BYTES = 2 * 1024 * 1024

_ENV_ALLOWLIST = (
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMDATA", "LANG", "LC_ALL", "FONTCONFIG_PATH",
)

_PROFILE_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
</oor:items>
"""


class PptxToPdfError(Exception):
    """Client-safe failure. The router converts it to an HTTPException."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PptxToPdfResult:
    pdf_path: Path
    page_count: int
    size_bytes: int


def find_soffice(configured: str = "") -> Path | None:
    """Locate LibreOffice: configured path, then PATH, then standard install folders."""
    candidates: list[Path] = []
    if configured:
        cleaned = configured.strip().strip("'\"")
        if cleaned:
            p = Path(cleaned)
            candidates.append(p)
            # If configured path is a directory (e.g. /usr/lib/libreoffice or .../program)
            if p.is_dir():
                candidates.extend([
                    p / "soffice",
                    p / "soffice.exe",
                    p / "program" / "soffice",
                    p / "program" / "soffice.exe",
                ])

    for name in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    # Windows standard paths
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")

    # Linux & macOS standard paths
    standard_paths = [
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
        "/usr/local/bin/libreoffice",
        "/usr/local/bin/soffice",
        "/snap/bin/libreoffice",
        "/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for sp in standard_paths:
        candidates.append(Path(sp))

    # Check /opt/libreoffice*/program/soffice
    opt_dir = Path("/opt")
    if opt_dir.is_dir():
        try:
            candidates.extend(opt_dir.glob("libreoffice*/program/soffice"))
        except OSError:
            pass

    return next((p for p in candidates if p.is_file()), None)


def _has_external_content(zf: zipfile.ZipFile) -> bool:
    """True if a relationship pulls remote/linked content (hyperlinks are fine)."""
    for info in zf.infolist():
        if not info.filename.endswith(".rels"):
            continue
        if info.file_size > _MAX_RELS_BYTES:
            return True
        with zf.open(info) as fh:
            data = fh.read(_MAX_RELS_BYTES + 1)  # never trust the declared size
        if len(data) > _MAX_RELS_BYTES:
            return True
        for tag in _REL_TAG_RE.findall(data):
            if _EXTERNAL_RE.search(tag):
                match = _TYPE_RE.search(tag)
                if not (match and match.group(1).endswith(b"/hyperlink")):
                    return True
    return False


def validate_presentation(
    path: Path,
    extension: str,
    *,
    max_slides: int,
    max_uncompressed_bytes: int,
    max_entries: int = 5000,
) -> int | None:
    """Check the real file signature. Returns the slide count (None for .ppt)."""
    invalid = PptxToPdfError("Only valid PPT or PPTX files are supported.", 400)
    with path.open("rb") as fh:
        head = fh.read(8)

    if extension == ".ppt":
        if head != _OLE_MAGIC:
            raise invalid
        return None  # legacy binary format: slide count is not cheaply readable

    if not head.startswith(_ZIP_MAGIC):
        raise invalid
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > max_entries:
                raise PptxToPdfError("The presentation is too complex to process.", 413)
            names = {i.filename.replace("\\", "/") for i in infos}
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                raise invalid
            if any(n.startswith("/") or ".." in Path(n).parts for n in names):
                raise invalid
            if sum(i.file_size for i in infos) > max_uncompressed_bytes:
                raise PptxToPdfError("The presentation is too large to process.", 413)
            if _has_external_content(zf):
                raise PptxToPdfError(
                    "Presentations with externally linked content are not supported.", 400
                )
            slides = sum(1 for n in names if _SLIDE_RE.fullmatch(n))
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        raise invalid from exc
    if slides < 1:
        raise PptxToPdfError("The presentation has no slides.", 400)
    if slides > max_slides:
        raise PptxToPdfError("Presentation contains too many slides.", 413)
    return slides


def _build_env(work_dir: Path) -> dict[str, str]:
    """Minimal environment: no inherited secrets, user dirs confined to the job folder."""
    env = {k: v for k in _ENV_ALLOWLIST if (v := os.environ.get(k))}
    home, tmp = work_dir / "home", work_dir / "tmp"
    for d in (home, tmp, home / "AppData" / "Roaming", home / "AppData" / "Local"):
        d.mkdir(parents=True, exist_ok=True)
    env.update(
        HOME=str(home), USERPROFILE=str(home),
        APPDATA=str(home / "AppData" / "Roaming"),
        LOCALAPPDATA=str(home / "AppData" / "Local"),
        TEMP=str(tmp), TMP=str(tmp), TMPDIR=str(tmp),
    )
    return env


def _write_profile(profile_dir: Path) -> None:
    user = profile_dir / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(_PROFILE_XCU, encoding="utf-8")


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":  # soffice.exe spawns soffice.bin; kill both
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, check=False, timeout=15,
            )
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        proc.kill()


def _looks_like_pdf(path: Path) -> bool:
    size = path.stat().st_size
    if size == 0:
        return False
    with path.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            return False
        fh.seek(max(0, size - 1024))
        return b"%%EOF" in fh.read()


def cleanup_stale_dirs(max_age_minutes: int = 60) -> int:
    """Remove temp folders leaked by a crashed worker. Call once at startup."""
    removed = 0
    cutoff = time.time() - max_age_minutes * 60
    for path in Path(tempfile.gettempdir()).glob(f"{TEMP_PREFIX}*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("Removed %d stale PPTX conversion folders", removed)
    return removed


def convert_presentation_to_pdf(
    input_path: Path,
    work_dir: Path,
    *,
    job_id: str = "-",
    soffice_path: str = "",
    timeout: int = 120,
    max_slides: int = 300,
    max_uncompressed_bytes: int = 500 * 1024 * 1024,
    max_entries: int = 5000,
    max_output_bytes: int = 300 * 1024 * 1024,
) -> PptxToPdfResult:
    """Convert input.ppt / input.pptx (server-named file) to PDF with LibreOffice."""
    started = time.perf_counter()
    extension = input_path.suffix.lower()
    slides = validate_presentation(
        input_path, extension, max_slides=max_slides,
        max_uncompressed_bytes=max_uncompressed_bytes, max_entries=max_entries,
    )
    soffice = find_soffice(soffice_path)
    if soffice is None:
        logger.error("[%s] LibreOffice not found; please install LibreOffice (e.g. 'sudo apt install libreoffice') or set PPTX_PDF_SOFFICE_PATH", job_id)
        raise PptxToPdfError(
            "The PowerPoint conversion engine (LibreOffice) is not installed or found on the server. "
            "Please install LibreOffice or set PPTX_PDF_SOFFICE_PATH.",
            503,
        )

    profile_dir = work_dir / "lo-profile"  # isolated per job, so jobs never collide
    out_dir = work_dir / "out"
    out_dir.mkdir(exist_ok=True)
    _write_profile(profile_dir)
    cmd = [  # list form, no shell: nothing from the client reaches the command line
        str(soffice),
        f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
        "--headless", "--norestore", "--nolockcheck", "--nodefault",
        "--nologo", "--nofirststartwizard",
        "--convert-to", "pdf:impress_pdf_Export",
        "--outdir", str(out_dir),
        str(input_path),
    ]
    logger.info("[%s] Presentation to PDF started: ext=%s slides=%s", job_id, extension, slides)
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_build_env(work_dir), cwd=str(work_dir),
            start_new_session=(sys.platform != "win32"),
        )
    except OSError as exc:
        logger.exception("[%s] Could not start LibreOffice", job_id)
        raise PptxToPdfError("Presentation conversion failed.", 500) from exc

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        logger.error("[%s] LibreOffice timed out after %ds", job_id, timeout)
        raise PptxToPdfError("The conversion took too long and was cancelled.", 504)
    except BaseException:
        _kill_tree(proc)
        raise

    output = (stdout + b"\n" + stderr).decode("utf-8", "replace")
    pdf_path = out_dir / f"{input_path.stem}.pdf"
    # Exit code 0 does not prove success: LibreOffice can exit 0 without output.
    if proc.returncode != 0 or not pdf_path.is_file():
        logger.error("[%s] LibreOffice failed rc=%s output=%s",
                     job_id, proc.returncode, output.strip()[-1000:])
        if "could not be loaded" in output.lower():
            raise PptxToPdfError("The file is not a valid PowerPoint presentation.", 422)
        raise PptxToPdfError("Presentation conversion failed.", 500)

    size = pdf_path.stat().st_size
    if size > max_output_bytes:
        raise PptxToPdfError("The generated PDF is too large.", 413)
    if not _looks_like_pdf(pdf_path):
        logger.error("[%s] Generated file is not a valid PDF", job_id)
        raise PptxToPdfError("Presentation conversion failed.", 500)
    try:
        with fitz.open(pdf_path) as out:
            pages = out.page_count
    except Exception as exc:
        logger.exception("[%s] Output PDF is unreadable", job_id)
        raise PptxToPdfError("Presentation conversion failed.", 500) from exc
    if pages < 1:
        raise PptxToPdfError("Presentation conversion failed.", 500)

    logger.info("[%s] Conversion completed: pages=%d bytes=%d seconds=%.2f",
                job_id, pages, size, time.perf_counter() - started)
    return PptxToPdfResult(pdf_path, pages, size)