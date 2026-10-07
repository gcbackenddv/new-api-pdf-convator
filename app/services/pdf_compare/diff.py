"""High-level difference aggregation."""
from __future__ import annotations

from typing import List

from .models import ChangeType, Difference, PageDiff, Summary


def build_summary(diffs: List[Difference], page_diffs: List[PageDiff]) -> Summary:
    s = Summary()
    for d in diffs:
        if d.change_type == ChangeType.ADDED:
            s.added += 1
        elif d.change_type == ChangeType.DELETED:
            s.deleted += 1
        elif d.change_type == ChangeType.MODIFIED:
            s.modified += 1
        elif d.change_type == ChangeType.MOVED:
            s.moved += 1
        elif d.change_type == ChangeType.VISUAL:
            s.visual_changes += 1
    s.total_differences = len(diffs)
    return s
