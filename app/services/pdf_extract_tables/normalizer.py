"""Raw detections + words -> normalized Table; header detection; continuation merging.

Library independent: works on geometry and words only.
"""
from __future__ import annotations

import bisect
import dataclasses
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from app.services.pdf_extract_tables.errors import TableTooLargeError
from app.services.pdf_extract_tables.models import (
    BBox, Cell, DetectionMethod, RawTable, Table, Word, single_line,
)

EDGE_TOLERANCE_PT = 2.0
MIN_ROWS = 2
MIN_COLUMNS = 2
MAX_HEADER_ROWS = 3
LATTICE_MIN_NONEMPTY_CELLS = 2
STREAM_MIN_FILL_RATIO = 0.20
STREAM_MAX_AVG_CELL_CHARS = 200
SAME_LINE_FACTOR = 0.6

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]")
# Digits (\d covers Bengali digits too), optional currency and percent.
_NUMERIC_RE = re.compile(r"^[\s(\-+]*[$€£৳₹]?\s*\d[\d,.\s]*%?\)?\s*$")


def clean_text(text: str) -> str:
    """Strip zero-width characters and control characters (XLSX rejects controls; ZWS causes display bugs)."""
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = _CONTROL_RE.sub("", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def cluster_edges(values: Iterable[float], tolerance: float = EDGE_TOLERANCE_PT) -> list[float]:
    ordered = sorted(values)
    if not ordered:
        return []
    clusters = [[ordered[0]]]
    for v in ordered[1:]:
        if v - clusters[-1][-1] <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [sum(c) / len(c) for c in clusters]


def _nearest(edges: Sequence[float], value: float) -> int:
    i = bisect.bisect_left(edges, value)
    candidates = [j for j in (i - 1, i) if 0 <= j < len(edges)]
    return min(candidates, key=lambda j: abs(edges[j] - value))


def _join_words(words: list[Word]) -> str:
    if not words:
        return ""
    ordered = sorted(words, key=lambda w: (w.cy, w.x0))
    lines: list[list[Word]] = [[ordered[0]]]
    line_cy = ordered[0].cy
    for w in ordered[1:]:
        if abs(w.cy - line_cy) <= SAME_LINE_FACTOR * max(w.height, 1.0):
            lines[-1].append(w)
        else:
            lines.append([w])
            line_cy = w.cy
    return "\n".join(" ".join(w.text for w in sorted(line, key=lambda w: w.x0)) for line in lines)


def _is_numeric(text: str) -> bool:
    return bool(_NUMERIC_RE.match(text))


@dataclass(slots=True)
class _Proto:
    row: int
    column: int
    rowspan: int
    colspan: int
    bbox: BBox
    words: list[Word]


def build_table(
    raw: RawTable,
    words: Sequence[Word],
    *,
    page: int,
    page_size: tuple[float, float],
    ocr_used: bool,
    max_rows: int,
    max_columns: int,
) -> Table | None:
    """Return a normalized table, or ``None`` if the detection is not a plausible table."""
    xs = cluster_edges([b[0] for b in raw.cell_bboxes] + [b[2] for b in raw.cell_bboxes])
    ys = cluster_edges([b[1] for b in raw.cell_bboxes] + [b[3] for b in raw.cell_bboxes])
    columns, rows = len(xs) - 1, len(ys) - 1
    if rows < MIN_ROWS or columns < MIN_COLUMNS:
        return None
    if rows > max_rows or columns > max_columns:
        raise TableTooLargeError("table exceeds configured size limits")

    owner: dict[tuple[int, int], _Proto] = {}
    protos: list[_Proto] = []
    for b in raw.cell_bboxes:
        c0, c1, r0, r1 = _nearest(xs, b[0]), _nearest(xs, b[2]), _nearest(ys, b[1]), _nearest(ys, b[3])
        if c1 <= c0 or r1 <= r0:
            continue
        positions = [(r, c) for r in range(r0, r1) for c in range(c0, c1)]
        if any(p in owner for p in positions):     # overlapping/bad geometry: first one wins
            continue
        proto = _Proto(r0, c0, r1 - r0, c1 - c0, b, [])
        protos.append(proto)
        owner.update(dict.fromkeys(positions, proto))
    for r in range(rows):                           # positions without a cell become empty cells
        for c in range(columns):
            if (r, c) not in owner:
                proto = _Proto(r, c, 1, 1, (xs[c], ys[r], xs[c + 1], ys[r + 1]), [])
                protos.append(proto)
                owner[(r, c)] = proto

    tx0, ty0, tx1, ty1 = raw.bbox
    for w in words:
        cx, cy = w.cx, w.cy
        if not (tx0 - EDGE_TOLERANCE_PT <= cx <= tx1 + EDGE_TOLERANCE_PT
                and ty0 - EDGE_TOLERANCE_PT <= cy <= ty1 + EDGE_TOLERANCE_PT):
            continue
        c = bisect.bisect_right(xs, cx) - 1
        r = bisect.bisect_right(ys, cy) - 1
        if 0 <= c < columns and 0 <= r < rows:
            owner[(r, c)].words.append(w)

    if raw.method is DetectionMethod.TEXT:
        rows_with_text = [r for r in range(rows) if any(owner[(r, c)].words for c in range(columns))]
        cols_with_text = [c for c in range(columns) if any(owner[(r, c)].words for r in range(rows))]
        if len(rows_with_text) < MIN_ROWS or len(cols_with_text) < MIN_COLUMNS:
            return None
        row_map = {old_r: new_r for new_r, old_r in enumerate(rows_with_text)}
        col_map = {old_c: new_c for new_c, old_c in enumerate(cols_with_text)}

        cells = []
        for p in protos:
            if p.row in row_map and p.column in col_map:
                cells.append(Cell(
                    row=row_map[p.row],
                    column=col_map[p.column],
                    text=clean_text(_join_words(p.words)),
                    page=page,
                    bbox=p.bbox,
                    rowspan=1,
                    colspan=1,
                ))
        rows = len(rows_with_text)
        columns = len(cols_with_text)
        xs = [xs[c] for c in cols_with_text] + [xs[cols_with_text[-1] + 1]]
        ys = [ys[r] for r in rows_with_text] + [ys[rows_with_text[-1] + 1]]
    else:
        cells = [
            Cell(row=p.row, column=p.column, text=clean_text(_join_words(p.words)), page=page,
                 bbox=p.bbox, rowspan=p.rowspan, colspan=p.colspan)
            for p in protos
        ]

    # Detect table title in Row 0 or immediately above the table bounding box
    title_candidate = ""
    title_re = re.compile(
        r"^(table\s*\d*[:\.\-]?|schedule\s*[a-z0-9]*[:\.\-]?|exhibit\s*[a-z0-9]*[:\.\-]?|statement\s+of|summary\s+of)\b",
        re.IGNORECASE,
    )
    if rows > 2:
        row0_cells = [c for c in cells if c.row == 0 and c.text]
        row1_cells = [c for c in cells if c.row == 1 and c.text]
        row0_text = " ".join(c.text for c in row0_cells).strip()

        is_row0_title = False
        if title_re.search(row0_text):
            is_row0_title = True
        elif len(row0_cells) == 1 and len(row1_cells) >= 2:
            is_row0_title = True

        if is_row0_title and rows - 1 >= MIN_ROWS:
            title_candidate = row0_text
            cells = [dataclasses.replace(c, row=c.row - 1) for c in cells if c.row > 0]
            rows -= 1
            ys = ys[1:]

    # Check if the last row is actually the title/caption of a subsequent table
    if rows > 2:
        last_row_cells = [c for c in cells if c.row == rows - 1 and c.text]
        last_row_text = " ".join(c.text for c in last_row_cells).strip()
        if title_re.search(last_row_text) and rows - 1 >= MIN_ROWS:
            cells = [c for c in cells if c.row < rows - 1]
            rows -= 1
            ys = ys[:-1]

    if not title_candidate:
        tx0, ty0, tx1, ty1 = raw.bbox
        above_words = [
            w for w in words
            if (ty0 - 50.0 <= w.cy <= ty0 + 1.0)
            and (tx0 - 30.0 <= w.cx <= tx1 + 30.0)
        ]
        if above_words:
            above_text = clean_text(_join_words(above_words))
            if above_text and len(above_text.splitlines()) <= 2:
                title_candidate = single_line(above_text)

    cells = sorted(cells, key=lambda c: (c.row, c.column))
    if not _is_plausible(cells, rows, columns, raw.method):
        return None
    header_rows = detect_header_rows(cells, rows)
    cells = [dataclasses.replace(c, is_header=c.row < header_rows) for c in cells]
    return Table(
        number=0, pages=(page,), bboxes=(raw.bbox,), row_count=rows, column_count=columns,
        header_rows=header_rows, cells=tuple(cells), method=raw.method, ocr_used=ocr_used,
        column_edges=tuple(xs), page_size=page_size, title=title_candidate,
    )


def _is_plausible(cells: Sequence[Cell], rows: int, columns: int, method: DetectionMethod) -> bool:
    filled = [c for c in cells if c.text]
    if len(filled) < LATTICE_MIN_NONEMPTY_CELLS:
        return False
    if method is DetectionMethod.TEXT:
        fill_ratio = len(filled) / (rows * columns)
        avg_chars = sum(len(c.text) for c in filled) / len(filled)
        if fill_ratio < STREAM_MIN_FILL_RATIO or avg_chars > STREAM_MAX_AVG_CELL_CHARS:
            return False
        # Prevent prose paragraphs where almost every row has only 1 column populated
        rows_with_multiple_cols = sum(
            sum(bool(c.text) for c in cells if c.row == r) >= 2
            for r in range(rows)
        )
        if rows_with_multiple_cols < 1:
            return False
    return True


def detect_header_rows(cells: Sequence[Cell], row_count: int) -> int:
    """0 = no header; otherwise 1..MAX_HEADER_ROWS. Heuristic, documented in the API notes."""
    first = [c for c in cells if c.row == 0]
    filled = [c for c in first if c.text]
    if not filled or all(_is_numeric(c.text) for c in filled):
        return 0
    header_rows = 1
    tallest = max((c.rowspan for c in first), default=1)
    if tallest > 1:
        header_rows = min(tallest, MAX_HEADER_ROWS)
    elif any(c.colspan > 1 for c in first) and row_count > 2:
        second = [c for c in cells if c.row == 1 and c.text]
        if second and not all(_is_numeric(c.text) for c in second):
            header_rows = 2
    return max(1, min(header_rows, row_count - 1))


# ---------------------------------------------------------------- multi-page merge
def merge_continuations(
    tables: Sequence[Table], *, edge_ratio: float, align_tolerance: float, max_rows: int
) -> list[Table]:
    """Merge a table into the previous one only if every continuation condition holds."""
    merged: list[Table] = []
    previous_page: int | None = None
    for table in tables:
        first_on_page = table.pages[0] != previous_page
        previous_page = table.pages[0]
        if merged and first_on_page and _is_continuation(merged[-1], table, edge_ratio, align_tolerance, max_rows):
            merged[-1] = _merge_pair(merged[-1], table)
        else:
            merged.append(table)
    return merged


def _is_continuation(prev: Table, cur: Table, edge_ratio: float, align_tolerance: float, max_rows: int) -> bool:
    if cur.pages[0] != prev.pages[-1] + 1:
        return False                                  # must be on the very next page
    if prev.column_count != cur.column_count or len(prev.column_edges) != len(cur.column_edges):
        return False
    page_w, page_h = prev.page_size
    if page_w <= 0 or page_h <= 0:
        return False
    if prev.bboxes[-1][3] < page_h * (1 - edge_ratio):
        return False                                  # previous table does not reach the page bottom
    if cur.bboxes[0][1] > page_h * edge_ratio:
        return False                                  # next table does not start at the page top
    tol = align_tolerance * page_w
    if any(abs(a - b) > tol for a, b in zip(prev.column_edges, cur.column_edges)):
        return False
    return prev.row_count + cur.row_count <= max_rows


def _norm_row(row: Sequence[str]) -> tuple[str, ...]:
    return tuple(single_line(t).casefold() for t in row)


def _merge_pair(prev: Table, cur: Table) -> Table:
    drop = 0
    h = prev.header_rows
    if h and cur.row_count >= h:
        prev_m, cur_m = prev.matrix(), cur.matrix()
        if all(_norm_row(prev_m[i]) == _norm_row(cur_m[i]) for i in range(h)):
            drop = h                                  # repeated header on the continuation page
    shifted = [
        dataclasses.replace(c, row=c.row - drop + prev.row_count, is_header=False)
        for c in cur.cells if c.row >= drop
    ]
    return dataclasses.replace(
        prev,
        pages=prev.pages + cur.pages,
        bboxes=prev.bboxes + cur.bboxes,
        row_count=prev.row_count + cur.row_count - drop,
        cells=prev.cells + tuple(shifted),
        title=prev.title or cur.title,
    )