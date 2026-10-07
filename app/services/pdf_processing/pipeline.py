"""Shared job lifecycle – temp dirs, cleanup, concurrency guard."""
from __future__ import annotations

import logging
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)

# Simple process-local semaphore (enough for single-worker or low concurrency VPS)
import threading
_job_sem: threading.Semaphore | None = None


def _get_sem() -> threading.Semaphore:
    global _job_sem
    if _job_sem is None:
        _job_sem = threading.Semaphore(get_settings().MAX_CONCURRENT_JOBS)
    return _job_sem


def create_job_dir(prefix: str = "job") -> Tuple[str, Path]:
    settings = get_settings()
    job_id = str(uuid.uuid4())
    path = settings.OUTPUT_DIR / prefix / job_id
    path.mkdir(parents=True, exist_ok=False)
    (path / "output").mkdir()
    return job_id, path


def cleanup_job(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            logger.info("Cleaned job %s", path.name)
    except Exception as exc:
        logger.warning("Cleanup failed for %s: %s", path, exc)


@contextmanager
def job_context(prefix: str = "job") -> Generator[Tuple[str, Path], None, None]:
    """Acquire concurrency slot + create job dir; always cleanup on exit if needed."""
    sem = _get_sem()
    acquired = sem.acquire(blocking=True, timeout=get_settings().PROCESSING_TIMEOUT)
    if not acquired:
        raise RuntimeError("Server busy – too many concurrent PDF jobs.")
    job_id, path = create_job_dir(prefix)
    try:
        yield job_id, path
    finally:
        sem.release()
