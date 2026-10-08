"""Render the reconstructed table (not a PDF crop) with Pillow.

Fonts: set TABLE_IMAGE_FONT_PATH / TABLE_IMAGE_BENGALI_FONT_PATH or install Noto Sans Bengali
and DejaVu. Bengali conjuncts need Pillow built with libraqm; without it text is legible
but unshaped.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

from app.services.pdf_extract_tables.errors import ResourceLimitError
from app.services.pdf_extract_tables.exporters.base import ExportedFile, ExportSettings
from app.services.pdf_extract_tables.models import Cell, ImageFormat, Table, TableDocument

logger = logging.getLogger(__name__)

FONT_SIZE = 14
LINE_HEIGHT = FONT_SIZE + 6
PAD_X, PAD_Y = 8, 6
MIN_COL_PX, MAX_COL_PX = 40, 360
MAX_LINES = 6
MAX_CELL_CHARS = 400
JPEG_QUALITY = 90
HEADER_BG, BODY_BG, GRID, INK = (217, 225, 242), (255, 255, 255), (150, 150, 150), (20, 20, 20)

_LATIN_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
)
_BENGALI_FONTS = (
    "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansBengali-Regular.ttf",
    "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
)


def _has_bengali(text: str) -> bool:
    return any("\u0980" <= ch <= "\u09ff" for ch in text)


class _Fonts:
    def __init__(self, latin_path: str, bengali_path: str) -> None:
        layout = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
        self.latin = self._load(latin_path, _LATIN_FONTS, layout) or self._default()
        self.bengali = self._load(bengali_path, _BENGALI_FONTS, layout)
        if self.bengali is None:
            logger.warning("pdf_tables.image_no_bengali_font")
            self.bengali = self.latin

    @staticmethod
    def _load(configured: str, candidates: tuple[str, ...], layout) -> ImageFont.FreeTypeFont | None:
        for path in ([configured] if configured else []) + list(candidates):
            if path and Path(path).is_file():
                try:
                    return ImageFont.truetype(path, FONT_SIZE, layout_engine=layout)
                except OSError:
                    continue
        return None

    @staticmethod
    def _default():
        try:
            return ImageFont.load_default(size=FONT_SIZE)
        except TypeError:           # very old Pillow
            return ImageFont.load_default()

    def for_text(self, text: str):
        return self.bengali if _has_bengali(text) else self.latin


def _wrap(text: str, font, max_px: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = word if not current else f"{current} {word}"
            if font.getlength(candidate) <= max_px:
                current = candidate
                continue
            if current:
                lines.append(current)
            while font.getlength(word) > max_px and len(word) > 1:
                cut = len(word)
                while cut > 1 and font.getlength(word[:cut]) > max_px:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


class ImageExporter:
    def __init__(self, settings: ExportSettings) -> None:
        self._s = settings
        self._fonts: _Fonts | None = None

    def export(self, document: TableDocument, output_dir: Path) -> list[ExportedFile]:
        if self._fonts is None:
            self._fonts = _Fonts(self._s.latin_font_path, self._s.bengali_font_path)
        jpeg = self._s.image_format is ImageFormat.JPEG
        ext, media = ("jpg", "image/jpeg") if jpeg else ("png", "image/png")
        files: list[ExportedFile] = []
        for table in document.tables:
            image = self._render(table)
            path = output_dir / f"{table.table_id}.{ext}"
            if jpeg:
                image.save(path, format="JPEG", quality=JPEG_QUALITY)
            else:
                image.save(path, format="PNG")
            image.close()
            files.append(ExportedFile(path, path.name, media))
        return files

    def _render(self, table: Table) -> Image.Image:
        fonts = self._fonts
        assert fonts is not None
        rows = min(table.row_count, self._s.image_max_rows)
        hidden = table.row_count - rows
        cells = [c for c in table.cells if c.row < rows]
        cols = table.column_count

        # column widths from single-column cells, then widen for spanning cells
        col_w = [float(MIN_COL_PX)] * cols
        spanning: list[tuple[Cell, float]] = []
        for c in cells:
            text = c.text[:MAX_CELL_CHARS]
            font = fonts.for_text(text)
            natural = max((font.getlength(line) for line in text.split("\n")), default=0.0) + 2 * PAD_X
            if c.colspan == 1:
                col_w[c.column] = max(col_w[c.column], min(natural, MAX_COL_PX))
            else:
                spanning.append((c, natural))
        for c, natural in spanning:
            end = min(c.column + c.colspan, cols)
            have = sum(col_w[c.column:end])
            if natural > have:
                col_w[end - 1] += min(natural, MAX_COL_PX * (end - c.column)) - have

        x_off = [0.0]
        for w in col_w:
            x_off.append(x_off[-1] + w)

        # wrap, then row heights
        wrapped: dict[int, list[str]] = {}
        row_h = [float(LINE_HEIGHT + 2 * PAD_Y)] * rows
        for idx, c in enumerate(cells):
            end = min(c.column + c.colspan, cols)
            text = c.text[:MAX_CELL_CHARS]
            lines = _wrap(text, fonts.for_text(text), x_off[end] - x_off[c.column] - 2 * PAD_X)
            wrapped[idx] = lines
            need = len(lines) * LINE_HEIGHT + 2 * PAD_Y
            last_row = min(c.row + c.rowspan, rows) - 1
            span_h = sum(row_h[c.row:last_row + 1])
            if need > span_h:
                row_h[last_row] += need - span_h
        title_text = table.title or f"Table {table.number}"
        title_h = float(LINE_HEIGHT + 2 * PAD_Y) if title_text else 0.0

        y_off = [0.0]
        for h in row_h:
            y_off.append(y_off[-1] + h)
        footer_h = LINE_HEIGHT + 2 * PAD_Y if hidden else 0

        width, height = int(x_off[-1]) + 1, int(y_off[-1] + title_h + footer_h) + 1
        if width * height > self._s.image_max_pixels:
            raise ResourceLimitError(
                "A table is too large to render as an image; choose another output format or fewer tables."
            )

        image = Image.new("RGB", (width, height), BODY_BG)
        draw = ImageDraw.Draw(image)

        if title_text:
            draw.rectangle([0, 0, width, title_h], fill=(226, 232, 240), outline=GRID)
            font_title = fonts.for_text(title_text)
            draw.text((PAD_X, PAD_Y), title_text, fill=INK, font=font_title)

        for idx, c in enumerate(cells):
            x0, x1 = x_off[c.column], x_off[min(c.column + c.colspan, cols)]
            y0, y1 = y_off[c.row] + title_h, y_off[min(c.row + c.rowspan, rows)] + title_h
            draw.rectangle([x0, y0, x1, y1], fill=HEADER_BG if c.is_header else BODY_BG, outline=GRID)
            font = fonts.for_text(c.text)
            for i, line in enumerate(wrapped[idx]):
                draw.text((x0 + PAD_X, y0 + PAD_Y + i * LINE_HEIGHT), line, fill=INK, font=font)
        if hidden:
            draw.text((PAD_X, y_off[-1] + title_h + PAD_Y), f"… {hidden} more rows not shown", fill=INK, font=fonts.latin)
        return image