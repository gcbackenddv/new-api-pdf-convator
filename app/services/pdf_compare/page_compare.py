"""Page matching – detect added / deleted / reordered pages."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from .text_compare import similarity_ratio, extract_page_text
from .visual_compare import visual_similarity
from app.services.pdf_processing.renderer import render_page_to_image

logger = logging.getLogger(__name__)


def match_pages(
    doc_old,
    doc_new,
    *,
    text_weight: float = 0.7,
    visual_weight: float = 0.3,
    match_threshold: float = 0.55,
) -> List[Tuple[Optional[int], Optional[int], float]]:
    """
    Match pages between two documents.
    Returns list of (old_idx, new_idx, score).
    Unmatched old pages → (idx, None, 0)
    Unmatched new pages → (None, idx, 0)
    Uses greedy best-match with text + light visual similarity.
    """
    n_old = doc_old.page_count
    n_new = doc_new.page_count

    # Pre-extract text
    texts_old = [extract_page_text(doc_old[i]) for i in range(n_old)]
    texts_new = [extract_page_text(doc_new[i]) for i in range(n_new)]

    # Similarity matrix (text only first – cheap)
    scores = [[0.0] * n_new for _ in range(n_old)]
    for i in range(n_old):
        for j in range(n_new):
            scores[i][j] = similarity_ratio(texts_old[i], texts_new[j])

    # Greedy matching
    used_old = set()
    used_new = set()
    matches: List[Tuple[int, int, float]] = []

    # Flatten and sort by score descending
    candidates = [
        (scores[i][j], i, j)
        for i in range(n_old)
        for j in range(n_new)
    ]
    candidates.sort(reverse=True)

    for score, i, j in candidates:
        if score < match_threshold:
            break
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        matches.append((i, j, score))

    result: List[Tuple[Optional[int], Optional[int], float]] = []
    for i, j, s in sorted(matches, key=lambda x: x[0]):
        result.append((i, j, s))

    for i in range(n_old):
        if i not in used_old:
            result.append((i, None, 0.0))
    for j in range(n_new):
        if j not in used_new:
            result.append((None, j, 0.0))

    return result
