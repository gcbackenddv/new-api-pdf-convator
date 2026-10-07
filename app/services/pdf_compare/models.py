"""Data models for PDF comparison results."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    MOVED = "moved"
    VISUAL = "visual"


class Difference(BaseModel):
    change_type: ChangeType
    page_old: Optional[int] = None
    page_new: Optional[int] = None
    description: str
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    bbox_old: Optional[List[float]] = None
    bbox_new: Optional[List[float]] = None
    severity: str = "medium"  # low|medium|high


class PageDiff(BaseModel):
    page_old: Optional[int] = None
    page_new: Optional[int] = None
    status: str  # matched|added|deleted|modified|moved
    text_similarity: float = 0.0
    visual_similarity: float = 0.0
    differences: List[Difference] = Field(default_factory=list)


class Summary(BaseModel):
    added: int = 0
    deleted: int = 0
    modified: int = 0
    moved: int = 0
    visual_changes: int = 0
    total_differences: int = 0


class CompareResult(BaseModel):
    success: bool = True
    pages_compared: int = 0
    summary: Summary = Field(default_factory=Summary)
    differences: List[Difference] = Field(default_factory=list)
    page_diffs: List[PageDiff] = Field(default_factory=list)
    reports: Dict[str, str] = Field(default_factory=dict)  # paths or inline content keys
