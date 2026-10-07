"""Text-level diff using difflib – Unicode / Bengali safe."""
from __future__ import annotations

import difflib
import logging
import re
from typing import List, Tuple

from .models import ChangeType, Difference

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Light normalization for comparison (preserve Unicode)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # collapse excessive whitespace but keep newlines
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_page_text(page) -> str:
    try:
        return page.get_text("text") or ""
    except Exception:
        return ""


def text_diff(
    old_text: str,
    new_text: str,
    *,
    page_old: int,
    page_new: int,
) -> List[Difference]:
    """Produce line-level added/deleted/modified differences."""
    old_lines = normalize_text(old_text).splitlines()
    new_lines = normalize_text(new_text).splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    diffs: List[Difference] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_chunk = "\n".join(old_lines[i1:i2])
        new_chunk = "\n".join(new_lines[j1:j2])

        if tag == "delete":
            diffs.append(
                Difference(
                    change_type=ChangeType.DELETED,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Deleted text on page {page_old}",
                    old_text=old_chunk[:500],
                    severity="medium",
                )
            )
        elif tag == "insert":
            diffs.append(
                Difference(
                    change_type=ChangeType.ADDED,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Added text on page {page_new}",
                    new_text=new_chunk[:500],
                    severity="medium",
                )
            )
        elif tag == "replace":
            # Heuristic: numeric/price change → higher severity
            severity = "high" if _looks_like_value_change(old_chunk, new_chunk) else "medium"
            diffs.append(
                Difference(
                    change_type=ChangeType.MODIFIED,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Modified text (page {page_old} → {page_new})",
                    old_text=old_chunk[:500],
                    new_text=new_chunk[:500],
                    severity=severity,
                )
            )
    return diffs


def _looks_like_value_change(old: str, new: str) -> bool:
    """Detect price / date / number changes."""
    num_re = re.compile(r"[\d,.]+")
    old_nums = num_re.findall(old)
    new_nums = num_re.findall(new)
    return bool(old_nums and new_nums and old_nums != new_nums)


def similarity_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()
