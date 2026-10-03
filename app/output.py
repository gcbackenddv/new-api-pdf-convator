import re
import shutil
import uuid
from pathlib import Path

from app.config import settings


def safe_stem(raw: str, fallback: str = "converted") -> str:
    base = Path(raw.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", Path(base).stem)[:80].strip("._")
    return cleaned or fallback


def save_output(source: Path, filename: str) -> Path:
    """Keep a uniquely named copy of a generated file in the project output directory."""
    output_dir = settings.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    requested = Path(filename)
    saved_path = output_dir / f"{requested.stem}-{uuid.uuid4().hex[:8]}{requested.suffix}"
    shutil.copy2(source, saved_path)
    return saved_path