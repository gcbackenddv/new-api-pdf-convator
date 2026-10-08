"""Text-level diff using difflib with bounding box localization – Unicode / Bengali safe."""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, List, Optional, Tuple

from .models import ChangeType, Difference

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Light normalization for comparison (preserve Unicode, strip zero-width chars)."""
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # collapse excessive spaces/tabs but keep newlines
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_page_text(page) -> str:
    try:
        raw = page.get_text("text") or ""
        return normalize_text(raw)
    except Exception:
        return ""


def find_text_bbox(page, text_chunk: str) -> Optional[List[float]]:
    """Locate the bounding box of a text chunk on a PyMuPDF page."""
    if not text_chunk or not hasattr(page, "search_for"):
        return None

    clean = normalize_text(text_chunk)
    if not clean:
        return None

    first_line = clean.splitlines()[0].strip()
    if not first_line:
        return None

    # First attempt: direct search_for on the line or sub-line
    sub = first_line[:60]
    rects = page.search_for(sub)
    if rects:
        r = rects[0]
        return [float(r.x0), float(r.y0), float(r.x1), float(r.y1)]

    # Second attempt: search by words tokens
    tokens = [t.lower() for t in sub.split() if t]
    if not tokens:
        return None

    try:
        raw_words = page.get_text("words")
    except Exception:
        return None

    words = [
        (w[0], w[1], w[2], w[3], w[4].replace("\u200b", "").replace("\ufeff", "").lower())
        for w in raw_words if w[4].strip()
    ]

    for i in range(len(words) - len(tokens) + 1):
        if all(tokens[k] in words[i + k][4] or words[i + k][4] in tokens[k] for k in range(len(tokens))):
            match_subset = words[i:i + len(tokens)]
            x0 = min(w[0] for w in match_subset)
            y0 = min(w[1] for w in match_subset)
            x1 = max(w[2] for w in match_subset)
            y1 = max(w[3] for w in match_subset)
            return [float(x0), float(y0), float(x1), float(y1)]

    return None


def text_diff(
    old_text: str,
    new_text: str,
    *,
    page_old: int,
    page_new: int,
    fitz_page_old: Any = None,
    fitz_page_new: Any = None,
) -> List[Difference]:
    """Produce line-level added/deleted/modified differences with bounding boxes."""
    old_lines = [l for l in normalize_text(old_text).splitlines() if l.strip()]
    new_lines = [l for l in normalize_text(new_text).splitlines() if l.strip()]

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    diffs: List[Difference] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_chunk = "\n".join(old_lines[i1:i2])
        new_chunk = "\n".join(new_lines[j1:j2])

        bbox_o = find_text_bbox(fitz_page_old, old_chunk) if fitz_page_old else None
        bbox_n = find_text_bbox(fitz_page_new, new_chunk) if fitz_page_new else None

        if tag == "delete":
            diffs.append(
                Difference(
                    change_type=ChangeType.DELETED,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Deleted text on page {page_old}",
                    old_text=old_chunk[:500],
                    bbox_old=bbox_o,
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
                    bbox_new=bbox_n,
                    severity="medium",
                )
            )
        elif tag == "replace":
            # Heuristic: numeric/price change -> higher severity
            severity = "high" if _looks_like_value_change(old_chunk, new_chunk) else "medium"
            diffs.append(
                Difference(
                    change_type=ChangeType.MODIFIED,
                    page_old=page_old,
                    page_new=page_new,
                    description=f"Modified text (page {page_old} → {page_new})",
                    old_text=old_chunk[:500],
                    new_text=new_chunk[:500],
                    bbox_old=bbox_o,
                    bbox_new=bbox_n,
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
