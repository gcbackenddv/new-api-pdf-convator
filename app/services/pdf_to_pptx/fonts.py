import logging
import re
import unicodedata
from typing import Any
from pptx.dml.color import RGBColor

logger = logging.getLogger(__name__)

# Known font mapping families to standard Cross-Platform / Microsoft Office fonts
# Known font mapping families to standard Cross-Platform / Microsoft Office fonts
FONT_FAMILY_MAP = {
    # Standard Serifs
    "times": "Times New Roman",
    "timesnewroman": "Times New Roman",
    "times-roman": "Times New Roman",
    "timesnewromanps": "Times New Roman",
    "liberationserif": "Times New Roman",
    "dejavuserif": "DejaVu Serif",
    "georgia": "Georgia",
    "garamond": "Garamond",
    "palatino": "Palatino Linotype",
    "palatinolinotype": "Palatino Linotype",
    "bookantiqua": "Book Antiqua",
    "cambria": "Cambria",
    "baskerville": "Baskerville Old Face",
    "playfairdisplay": "Playfair Display",
    "merriweather": "Merriweather",
    "lora": "Lora",
    "cinzel": "Cinzel",
    # Standard Sans-Serifs & Weight Variants
    "arial": "Arial",
    "arialmt": "Arial",
    "arialnarrow": "Arial Narrow",
    "arialblack": "Arial Black",
    "helvetica": "Arial",
    "helveticaneue": "Helvetica Neue",
    "helveticaneuelight": "Helvetica Neue Light",
    "helveticaneuemedium": "Helvetica Neue Medium",
    "liberationsans": "Liberation Sans",
    "dejavusans": "DejaVu Sans",
    "nimbussans": "Arial",
    "calibri": "Calibri",
    "calibrilight": "Calibri Light",
    "aptos": "Aptos",
    "verdana": "Verdana",
    "tahoma": "Tahoma",
    "trebuchet": "Trebuchet MS",
    "trebuchetms": "Trebuchet MS",
    "centurygothic": "Century Gothic",
    "franklingothic": "Franklin Gothic Medium",
    "franklingothicmedium": "Franklin Gothic Medium",
    "gillsans": "Gill Sans MT",
    "gillsansmt": "Gill Sans MT",
    "twcenmt": "Tw Cen MT",
    "futura": "Century Gothic",
    "avenir": "Segoe UI",
    "comicsans": "Comic Sans MS",
    "segoeui": "Segoe UI",
    "segoe": "Segoe UI",
    "segoeuilight": "Segoe UI Light",
    "segoeuisemibold": "Segoe UI Semibold",
    "segoeuiblack": "Segoe UI Black",
    "roboto": "Roboto",
    "robotolight": "Roboto Light",
    "robotothin": "Roboto Thin",
    "robotomedium": "Roboto Medium",
    "robotoblack": "Roboto Black",
    "opensans": "Open Sans",
    "opensanslight": "Open Sans Light",
    "opensanssemibold": "Open Sans SemiBold",
    "opensansextrabold": "Open Sans ExtraBold",
    "lato": "Lato",
    "latolight": "Lato Light",
    "latothin": "Lato Thin",
    "latoblack": "Lato Black",
    "montserrat": "Montserrat",
    "montserratlight": "Montserrat Light",
    "montserratmedium": "Montserrat Medium",
    "montserratsemibold": "Montserrat SemiBold",
    "montserratblack": "Montserrat Black",
    "montserratextrabold": "Montserrat ExtraBold",
    "poppins": "Poppins",
    "poppinslight": "Poppins Light",
    "poppinsmedium": "Poppins Medium",
    "poppinssemibold": "Poppins SemiBold",
    "inter": "Inter",
    "raleway": "Raleway",
    "oswald": "Oswald",
    "nunito": "Nunito",
    "rubik": "Rubik",
    "dmsans": "DM Sans",
    "impact": "Impact",
    "copperplate": "Copperplate Gothic Bold",
    # Monospaced
    "courier": "Courier New",
    "couriernew": "Courier New",
    "liberationmono": "Courier New",
    "nimbusmono": "Courier New",
    "consolas": "Consolas",
    "sourcecodepro": "Source Code Pro",
    "firamono": "Fira Mono",
    "firacode": "Fira Code",
    "dejavusansmono": "DejaVu Sans Mono",
    # Indic / Bengali fonts
    "kalpurush": "Kalpurush",
    "solaimanlipi": "SolaimanLipi",
    "bangla": "Kalpurush",
    "siyamrupali": "Siyam Rupali",
    "nirmala": "Nirmala UI",
    "vrinda": "Vrinda",
    "notosans": "Noto Sans",
    "notoserif": "Noto Serif",
}

STYLE_SUFFIX_PATTERN = re.compile(
    r"[-_, ]*(regular|bold|italic|oblique|roman|mt|psmt)$",
    re.IGNORECASE,
)

# Fonts that represent symbol sets, icons, or glyph bullets rather than standard text
SYMBOL_FONT_KEYWORDS = (
    "wingdings",
    "webdings",
    "dingbats",
    "symbol",
    "marlett",
    "fontawesome",
    "font-awesome",
    "material",
    "icomoon",
    "typicons",
    "glyphicons",
    "bullets",
    "zapfdingbats",
    "mtextra",
)

# Invalid XML 1.0 characters regex
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")


# Map common PDF Private Use Area (PUA) bullet and icon glyphs to standard Unicode characters
PUA_TO_UNICODE = {
    "\uf0b7": "• ",  # Symbol/Wingdings standard bullet point
    "\uf0a7": "▪ ",  # Small square bullet
    "\uf0d8": "➢ ",  # Arrow bullet
    "\uf0fc": "✔ ",  # Check mark
    "\uf0e0": "✉ ",  # Envelope
    "\uf020": " ",
    "\uf0a0": " ",
}


def clean_xml_string(text: str) -> str:
    """Removes invalid XML 1.0 characters and normalizes PUA bullets."""
    if not text:
        return ""
    # Map common PUA bullet and icon glyphs to standard Unicode
    for pua_char, std_char in PUA_TO_UNICODE.items():
        if pua_char in text:
            text = text.replace(pua_char, std_char)
    # Remove control characters, replacement chars, and null bytes
    cleaned = _INVALID_XML_CHARS.sub("", text)
    # Replace non-breaking spaces with normal spaces
    cleaned = cleaned.replace("\u00a0", " ").replace("\u202f", " ")
    # Remove soft hyphens
    cleaned = cleaned.replace("\u00ad", "")
    return cleaned


def is_symbol_or_icon_font(font_name: str) -> bool:
    """Checks whether a font is a symbol or icon font."""
    name_lower = (font_name or "").lower()
    return any(keyword in name_lower for keyword in SYMBOL_FONT_KEYWORDS)


def is_garbage_or_symbol_glyph(text: str, font_name: str) -> bool:
    """Detects whether text content is non-text graphical noise or unmapped PUA glyphs.

    Never treats graphical symbols, icon font glyphs, or unmapped private-use codes as text.
    Preserves mapped standard bullets and readable symbols.
    """
    if not text:
        return True

    # Check for mapped bullets or standard symbols
    has_valid_bullet = any(c in "•▪➢✔✉" for c in text)

    # If font is an icon/symbol font, allow only if mapped to a known bullet
    if is_symbol_or_icon_font(font_name):
        return not has_valid_bullet

    # Check for Private Use Area (PUA) characters or unmapped glyphs:
    # U+E000 to U+F8FF, U+F0000 to U+FFFFD, U+100000 to U+10FFFD
    pua_count = 0
    printable_count = 0
    for char in text:
        code = ord(char)
        if (0xE000 <= code <= 0xF8FF) or (0xF0000 <= code <= 0xFFFFD) or (0x100000 <= code <= 0x10FFFD):
            pua_count += 1
        elif unicodedata.category(char) not in ("Cc", "Cs", "Cn"):
            if not char.isspace():
                printable_count += 1

    # If string is entirely PUA or has no printable text, it is non-text graphical noise
    if printable_count == 0:
        return True
    if pua_count > 0 and (pua_count / len(text)) > 0.5:
        return True

    return False


def split_camel_case(name: str) -> str:
    """Splits CamelCase or PascalCase into spaced words (e.g. SourceCodePro -> Source Code Pro)."""
    s1 = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s1)
    return s2.strip()


def resolve_font_styling(
    pdf_font: str,
    flags: int = 0,
    default_font: str = "Calibri",
) -> tuple[str, bool, bool]:
    """Resolves exact font typeface name, bold style, and italic style from PDF font metadata.

    Preserves distinct font weights and subfamilies (e.g. Light, SemiBold, Black, Narrow, Condensed, Thin)
    as exact font names so PowerPoint renders the identical font style.
    Returns (font_name, is_bold, is_italic).
    """
    if not pdf_font:
        return default_font, False, False

    # 1. Remove PDF font subset prefix (e.g. 'ABCDEF+Oswald-Regular' -> 'Oswald-Regular')
    cleaned = re.sub(r"^[A-Z]{6}\+", "", pdf_font).strip()

    # 2. Detect bold and italic flags
    bold_flag = bool(flags & 16 or flags & 262144)
    name_has_bold = bool(re.search(r"[-_, ]*(bold|heavy|black|bld|extrabold|ultrabold)", cleaned, re.IGNORECASE))
    is_bold_res = bold_flag or name_has_bold

    italic_flag = bool(flags & 2 or flags & 65536)
    name_has_italic = bool(re.search(r"[-_, ]*(italic|oblique|slanted|ita)", cleaned, re.IGNORECASE))
    is_italic_res = italic_flag or name_has_italic

    # 3. Check exact match in FONT_FAMILY_MAP
    simplified = re.sub(r"[^a-zA-Z]", "", cleaned).lower()
    if simplified in FONT_FAMILY_MAP:
        return FONT_FAMILY_MAP[simplified], is_bold_res, is_italic_res

    # 4. Strip pure style suffixes (bold, italic, regular, psmt, mt, roman)
    base_name = cleaned
    prev = None
    while prev != base_name:
        prev = base_name
        base_name = STYLE_SUFFIX_PATTERN.sub("", base_name).strip()

    base_simplified = re.sub(r"[^a-zA-Z]", "", base_name).lower()
    if base_simplified in FONT_FAMILY_MAP:
        return FONT_FAMILY_MAP[base_simplified], is_bold_res, is_italic_res

    # Check prefix matches in FONT_FAMILY_MAP (prefer longest keys)
    for key in sorted(FONT_FAMILY_MAP.keys(), key=len, reverse=True):
        if len(key) >= 4 and key in base_simplified:
            mapped = FONT_FAMILY_MAP[key]
            for weight in ("Light", "Thin", "Medium", "SemiBold", "Black", "ExtraBold", "Narrow", "Condensed"):
                if weight.lower() in base_simplified and weight.lower() not in key:
                    mapped = f"{mapped} {weight}"
                    break
            return mapped, is_bold_res, is_italic_res

    # 5. Preserve custom typeface name
    if base_name and not is_symbol_or_icon_font(base_name):
        has_letters = any(c.isalpha() for c in base_name)
        if has_letters:
            return split_camel_case(base_name.replace("-", " ").replace("_", " ")), is_bold_res, is_italic_res

    return default_font or "Calibri", is_bold_res, is_italic_res


def normalize_font_name(pdf_font: str, default_font: str = "Calibri") -> str:
    """Safely extracts and preserves exact font family names from PDF fonts."""
    font_name, _, _ = resolve_font_styling(pdf_font, 0, default_font)
    return font_name


def is_bold(flags: int, font_name: str) -> bool:
    """Detect bold style from PyMuPDF flags or font name."""
    name_lower = (font_name or "").lower()
    if flags & 16 or flags & 262144:  # PyMuPDF bold flag / heavy
        return True
    return any(term in name_lower for term in ("bold", "black", "heavy", "semibold", "bld", "medium"))


def is_italic(flags: int, font_name: str) -> bool:
    """Detect italic style from PyMuPDF flags or font name."""
    name_lower = (font_name or "").lower()
    if flags & 2 or flags & 65536:  # PyMuPDF italic flag / oblique
        return True
    return any(term in name_lower for term in ("italic", "oblique", "slanted", "ita"))


def parse_color(raw_color: Any) -> RGBColor:
    """Parse color into a python-pptx RGBColor safely, supporting RGB, Grayscale, and CMYK."""
    try:
        if isinstance(raw_color, int):
            r = (raw_color >> 16) & 0xFF
            g = (raw_color >> 8) & 0xFF
            b = raw_color & 0xFF
            return RGBColor(r, g, b)

        if isinstance(raw_color, (list, tuple)):
            if len(raw_color) == 4:
                # CMYK color: c, m, y, k (usually 0.0-1.0 floats)
                c, m, y, k = raw_color
                c_val = float(c) if float(c) <= 1.0 else float(c) / 100.0
                m_val = float(m) if float(m) <= 1.0 else float(m) / 100.0
                y_val = float(y) if float(y) <= 1.0 else float(y) / 100.0
                k_val = float(k) if float(k) <= 1.0 else float(k) / 100.0
                r = int(255 * (1.0 - c_val) * (1.0 - k_val))
                g = int(255 * (1.0 - m_val) * (1.0 - k_val))
                b = int(255 * (1.0 - y_val) * (1.0 - k_val))
                return RGBColor(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

            if len(raw_color) >= 3:
                r, g, b = raw_color[0], raw_color[1], raw_color[2]
                if isinstance(r, float) and 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0:
                    return RGBColor(int(r * 255), int(g * 255), int(b * 255))
                return RGBColor(
                    max(0, min(255, int(r))),
                    max(0, min(255, int(g))),
                    max(0, min(255, int(b))),
                )

            if len(raw_color) == 1:  # Grayscale list
                v = int(raw_color[0] * 255) if isinstance(raw_color[0], float) and raw_color[0] <= 1.0 else int(raw_color[0])
                v = max(0, min(255, v))
                return RGBColor(v, v, v)

        if isinstance(raw_color, float):
            v = int(raw_color * 255) if raw_color <= 1.0 else int(raw_color)
            v = max(0, min(255, v))
            return RGBColor(v, v, v)
    except Exception as exc:
        logger.debug("Could not parse color %r: %s", raw_color, exc)

    return RGBColor(0, 0, 0)
