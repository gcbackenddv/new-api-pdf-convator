from dataclasses import dataclass
import math
from pptx.util import Emu
import fitz

EMU_PER_POINT = 12700
MAX_SLIDE_EMU = 50_000_000  # PowerPoint limit (~54.6 inches)
MIN_DIMENSION_EMU = 1000


def calculate_optimal_dpi(
    page: fitz.Page,
    target_dpi: int | None = None,
    *,
    min_dpi: int = 150,
    max_dpi: int = 300,
    max_pixels: int = 40_000_000,
) -> int:
    """Calculates optimal DPI for page rasterization, balancing high visual fidelity and VPS memory limits.

    If target_dpi is provided and > 0, clamps target_dpi to the memory ceiling.
    Otherwise, automatically computes DPI based on embedded image resolutions, vector complexity,
    scanned status, and page dimensions.
    """
    rect = page.rect
    w_pt = max(1.0, float(rect.width))
    h_pt = max(1.0, float(rect.height))

    # Calculate absolute memory ceiling based on max_pixels
    area_pt2 = w_pt * h_pt
    max_allowed_by_mem = int(math.floor(72.0 * math.sqrt(max_pixels / area_pt2)))
    effective_max_dpi = min(max_dpi, max(72, max_allowed_by_mem))

    if target_dpi is not None and target_dpi > 0:
        return min(target_dpi, effective_max_dpi)

    # Automatic calculation for high quality
    candidate_dpi = 200  # High-quality baseline

    # Check embedded images resolution
    image_dpis: list[float] = []
    try:
        for info in page.get_image_info(xrefs=True):
            bbox = info.get("bbox")
            w_px = info.get("width", 0)
            h_px = info.get("height", 0)
            if bbox and len(bbox) == 4 and w_px > 0 and h_px > 0:
                bw = abs(bbox[2] - bbox[0])
                bh = abs(bbox[3] - bbox[1])
                if bw > 1.0 and bh > 1.0:
                    dx = (w_px / bw) * 72.0
                    dy = (h_px / bh) * 72.0
                    image_dpis.append(max(dx, dy))
    except Exception:
        pass

    if image_dpis:
        max_img_dpi = max(image_dpis)
        # Match image resolution up to max_dpi
        candidate_dpi = max(candidate_dpi, min(max_dpi, int(round(max_img_dpi))))

    # Check vector drawings density (crisper rasterization for complex diagrams/curves)
    try:
        drawings = page.get_drawings()
        if len(drawings) > 0:
            candidate_dpi = max(candidate_dpi, 240)
        if len(drawings) > 20:
            candidate_dpi = max(candidate_dpi, 300)
    except Exception:
        pass

    # Check if page is textless or scanned (OCR benefits from 300 DPI)
    try:
        if not page.get_text().strip() and len(page.get_images()) > 0:
            candidate_dpi = max(candidate_dpi, 300)
    except Exception:
        pass

    final_dpi = max(min_dpi, min(candidate_dpi, effective_max_dpi))
    return final_dpi



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
