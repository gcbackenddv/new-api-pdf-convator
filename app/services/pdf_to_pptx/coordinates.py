from dataclasses import dataclass
from pptx.util import Emu
import fitz

EMU_PER_POINT = 12700
MAX_SLIDE_EMU = 50_000_000  # PowerPoint limit (~54.6 inches)
MIN_DIMENSION_EMU = 1000


@dataclass(frozen=True)
class SlideGeometry:
    """Calculates PowerPoint slide dimensions and translates PDF coordinates to PPTX EMUs."""
    page_rect: fitz.Rect
    scale: float
    slide_width: Emu
    slide_height: Emu
    offset_x: int = 0
    offset_y: int = 0

    @classmethod
    def from_page_rect(cls, rect: fitz.Rect) -> "SlideGeometry":
        width_pt = max(1.0, float(rect.width))
        height_pt = max(1.0, float(rect.height))
        max_pt = max(width_pt, height_pt)
        scale = min(1.0, MAX_SLIDE_EMU / (max_pt * EMU_PER_POINT))

        slide_w = Emu(int(width_pt * EMU_PER_POINT * scale))
        slide_h = Emu(int(height_pt * EMU_PER_POINT * scale))
        return cls(page_rect=rect, scale=scale, slide_width=slide_w, slide_height=slide_h, offset_x=0, offset_y=0)

    @classmethod
    def for_page(cls, page_rect: fitz.Rect, target_slide_w: Emu, target_slide_h: Emu) -> "SlideGeometry":
        """Calculates page geometry scaled and centered within target presentation slide dimensions."""
        width_pt = max(1.0, float(page_rect.width))
        height_pt = max(1.0, float(page_rect.height))

        scale_x = float(target_slide_w) / (width_pt * EMU_PER_POINT)
        scale_y = float(target_slide_h) / (height_pt * EMU_PER_POINT)
        scale = min(scale_x, scale_y)

        rendered_w = int(width_pt * EMU_PER_POINT * scale)
        rendered_h = int(height_pt * EMU_PER_POINT * scale)

        offset_x = max(0, (int(target_slide_w) - rendered_w) // 2)
        offset_y = max(0, (int(target_slide_h) - rendered_h) // 2)

        return cls(
            page_rect=page_rect,
            scale=scale,
            slide_width=target_slide_w,
            slide_height=target_slide_h,
            offset_x=offset_x,
            offset_y=offset_y,
        )

    def to_pptx_coords(self, x0: float, y0: float, x1: float, y1: float) -> tuple[Emu, Emu, Emu, Emu]:
        """Convert a PDF bounding box (x0, y0, x1, y1) in points to PPTX (left, top, width, height) in EMUs.

        Preserves exact positioning without clamping, allowing full-bleed bleed-off graphics.
        """
        norm_x0 = min(x0, x1)
        norm_x1 = max(x0, x1)
        norm_y0 = min(y0, y1)
        norm_y1 = max(y0, y1)

        left = self.offset_x + int((norm_x0 - self.page_rect.x0) * EMU_PER_POINT * self.scale)
        top = self.offset_y + int((norm_y0 - self.page_rect.y0) * EMU_PER_POINT * self.scale)
        width = max(MIN_DIMENSION_EMU, int((norm_x1 - norm_x0) * EMU_PER_POINT * self.scale))
        height = max(MIN_DIMENSION_EMU, int((norm_y1 - norm_y0) * EMU_PER_POINT * self.scale))

        return Emu(left), Emu(top), Emu(width), Emu(height)

    def pt_to_emu(self, pt_val: float) -> Emu:
        """Convert points to EMUs using the page scale."""
        return Emu(max(0, int(pt_val * EMU_PER_POINT * self.scale)))
