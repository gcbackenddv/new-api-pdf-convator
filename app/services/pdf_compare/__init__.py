"""Advanced PDF comparison – text, visual, page-level."""
from .comparator import compare_pdfs
from .models import CompareResult, Difference, PageDiff, Summary

__all__ = ["compare_pdfs", "CompareResult", "Difference", "PageDiff", "Summary"]
