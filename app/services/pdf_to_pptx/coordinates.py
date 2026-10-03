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

    @classmethod
    def from_page_rect(cls, rect: fitz.Rect) -> "SlideGeometry":
        width_pt = max(1.0, float(rect.width))
        height_pt = max(1.0, float(rect.height))
        max_pt = max(width_pt, height_pt)
        scale = min(1.0, MAX_SLIDE_EMU / (max_pt * EMU_PER_POINT))

        slide_w = Emu(int(width_pt * EMU_PER_POINT * scale))
        slide_h = Emu(int(height_pt * EMU_PER_POINT * scale))
        return cls(page_rect=rect, scale=scale, slide_width=slide_w, slide_height=slide_h)

    def to_pptx_coords(self, x0: float, y0: float, x1: float, y1: float) -> tuple[Emu, Emu, Emu, Emu]:
        """Convert a PDF bounding box (x0, y0, x1, y1) in points to PPTX (left, top, width, height) in EMUs."""
        norm_x0 = min(x0, x1)
        norm_x1 = max(x0, x1)
        norm_y0 = min(y0, y1)
        norm_y1 = max(y0, y1)

        left = max(0, int((norm_x0 - self.page_rect.x0) * EMU_PER_POINT * self.scale))
        top = max(0, int((norm_y0 - self.page_rect.y0) * EMU_PER_POINT * self.scale))
        width = max(MIN_DIMENSION_EMU, int((norm_x1 - norm_x0) * EMU_PER_POINT * self.scale))
        height = max(MIN_DIMENSION_EMU, int((norm_y1 - norm_y0) * EMU_PER_POINT * self.scale))

        return Emu(left), Emu(top), Emu(width), Emu(height)

    def pt_to_emu(self, pt_val: float) -> Emu:
        """Convert points to EMUs using the page scale."""
        return Emu(max(0, int(pt_val * EMU_PER_POINT * self.scale)))
