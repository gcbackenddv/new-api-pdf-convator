import logging
import re
from typing import Any
from pptx.dml.color import RGBColor

logger = logging.getLogger(__name__)

# Known font mapping families to standard Cross-Platform / Microsoft Office fonts
FONT_FAMILY_MAP = {
    "times": "Times New Roman",
    "timesnewroman": "Times New Roman",
    "times-roman": "Times New Roman",
    "timesnewromanps": "Times New Roman",
    "liberationserif": "Times New Roman",
    "arial": "Arial",
    "helvetica": "Arial",
    "liberationsans": "Arial",
    "nimbussans": "Arial",
    "arialmt": "Arial",
    "calibri": "Calibri",
    "courier": "Courier New",
    "couriernew": "Courier New",
    "liberationmono": "Courier New",
    "nimbusmono": "Courier New",
    "georgia": "Georgia",
    "verdana": "Verdana",
    "tahoma": "Tahoma",
    "trebuchet": "Trebuchet MS",
    "comicsans": "Comic Sans MS",
    "segoeui": "Segoe UI",
    "segoe": "Segoe UI",
    "roboto": "Roboto",
    "opensans": "Open Sans",
    "lato": "Lato",
    "montserrat": "Montserrat",
    "kalpurush": "Kalpurush",
    "solaimanlipi": "SolaimanLipi",
    "bangla": "Kalpurush",
    "siyamrupali": "Siyam Rupali",
    "nirmala": "Nirmala UI",
    "vrinda": "Vrinda",
}


def normalize_font_name(pdf_font: str, default_font: str = "Calibri") -> str:
    """Safely maps PDF embedded font names to available presentation fonts with fallback."""
    if not pdf_font:
        return default_font

    # Remove PDF font subset prefix (e.g. 'ABCDEF+Calibri' -> 'Calibri')
    cleaned = re.sub(r"^[A-Z]{6}\+", "", pdf_font).strip()

    # Normalize lookup key (lowercase, alphanumeric only)
    simplified = re.sub(r"[^a-zA-Z]", "", cleaned).lower()

    for key, mapped_name in FONT_FAMILY_MAP.items():
        if key in simplified:
            return mapped_name

    logger.debug("Font '%s' mapped to default fallback '%s'", pdf_font, default_font)
    return default_font or "Calibri"


def is_bold(flags: int, font_name: str) -> bool:
    """Detect bold style from PyMuPDF flags or font name."""
    name_lower = (font_name or "").lower()
    if flags & 16 or flags & 262144:  # PyMuPDF bold flag / heavy
        return True
    return any(term in name_lower for term in ("bold", "black", "heavy", "semibold", "bld"))


def is_italic(flags: int, font_name: str) -> bool:
    """Detect italic style from PyMuPDF flags or font name."""
    name_lower = (font_name or "").lower()
    if flags & 2 or flags & 65536:  # PyMuPDF italic flag / oblique
        return True
    return any(term in name_lower for term in ("italic", "oblique", "slanted", "ita"))


def parse_color(raw_color: Any) -> RGBColor:
    """Parse color into a python-pptx RGBColor safely."""
    try:
        if isinstance(raw_color, int):
            r = (raw_color >> 16) & 0xFF
            g = (raw_color >> 8) & 0xFF
            b = raw_color & 0xFF
            return RGBColor(r, g, b)

        if isinstance(raw_color, (list, tuple)):
            if len(raw_color) >= 3:
                # Can be 0.0-1.0 floats or 0-255 ints
                r, g, b = raw_color[0], raw_color[1], raw_color[2]
                if isinstance(r, float) and 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0:
                    return RGBColor(int(r * 255), int(g * 255), int(b * 255))
                return RGBColor(
                    max(0, min(255, int(r))),
                    max(0, min(255, int(g))),
                    max(0, min(255, int(b))),
                )
            if len(raw_color) == 1:  # Grayscale
                v = int(raw_color[0] * 255) if isinstance(raw_color[0], float) else int(raw_color[0])
                v = max(0, min(255, v))
                return RGBColor(v, v, v)
    except Exception as exc:
        logger.debug("Could not parse color %r: %s", raw_color, exc)

    return RGBColor(0, 0, 0)
