"""Font embedder for PowerPoint presentations.

Extracts embedded font programs (TrueType / OpenType) from the source PDF document
and embeds them directly into the PPTX OpenXML package (<p:embeddedFontList>).
Ensures that recipient machines render the exact same typography and font styling
even if the font is not installed on the system.
"""
from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Namespaces for PPTX OpenXML
PRESENTATIONML_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
FONT_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"


def _clean_font_name(raw_name: str) -> str:
    """Strips PDF subset tag (e.g. 'ABCDEF+Roboto-Bold' -> 'Roboto-Bold')."""
    if not raw_name:
        return "Unknown"
    return re.sub(r"^[A-Z]{6}\+", "", raw_name).strip()


def embed_fonts_from_pdf(doc: fitz.Document, pptx_path: Path) -> int:
    """Extracts embedded TrueType / OpenType fonts from PDF and embeds them into the PPTX package.

    Returns the count of successfully embedded fonts.
    """
    pptx_path = Path(pptx_path)
    if not pptx_path.exists() or pptx_path.stat().st_size == 0:
        return 0

    # 1. Collect all embedded fonts from the PDF
    extracted_fonts: dict[str, tuple[str, bytes]] = {}  # clean_name -> (ext, buffer)
    seen_xrefs: set[int] = set()

    for page_idx in range(len(doc)):
        try:
            page = doc[page_idx]
            for font_info in page.get_fonts(full=True):
                xref = font_info[0]
                if xref <= 0 or xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    name, ext, ftype, font_data = doc.extract_font(xref)
                    if font_data and len(font_data) > 100 and ext.lower() in ("ttf", "otf", "cff", "woff"):
                        clean_name = _clean_font_name(name)
                        if clean_name not in extracted_fonts:
                            extracted_fonts[clean_name] = (ext.lower(), font_data)
                except Exception as exc:
                    logger.debug("Could not extract font xref %d: %s", xref, exc)
        except Exception:
            pass

    if not extracted_fonts:
        return 0

    logger.info("Found %d embedded fonts in PDF to embed into PPTX: %s", len(extracted_fonts), list(extracted_fonts.keys()))

    # 2. Open PPTX archive and update OpenXML parts
    try:
        with zipfile.ZipFile(pptx_path, "r") as zin:
            file_map = {name: zin.read(name) for name in zin.namelist()}

        if "ppt/presentation.xml" not in file_map or "ppt/_rels/presentation.xml.rels" not in file_map:
            return 0

        # Update [Content_Types].xml
        ct_bytes = file_map.get("[Content_Types].xml", b"")
        ct_str = ct_bytes.decode("utf-8", errors="ignore")
        if 'Extension="fntdata"' not in ct_str:
            ct_str = ct_str.replace(
                "</Types>",
                '<Default Extension="fntdata" ContentType="application/x-fontdata"/></Types>',
            )
            file_map["[Content_Types].xml"] = ct_str.encode("utf-8")

        # Prepare relationships and embedded font elements
        rels_str = file_map["ppt/_rels/presentation.xml.rels"].decode("utf-8", errors="ignore")
        pres_str = file_map["ppt/presentation.xml"].decode("utf-8", errors="ignore")

        # Find maximum existing rId number in rels
        existing_rids = [int(m) for m in re.findall(r'Id="rId(\d+)"', rels_str)]
        next_rid_num = max(existing_rids, default=100) + 1

        embedded_font_xml_parts: list[str] = []
        new_rels_parts: list[str] = []

        font_index = 1
        for font_name, (ext, data) in extracted_fonts.items():
            font_file_name = f"fonts/font{font_index}.fntdata"
            file_map[f"ppt/{font_file_name}"] = data

            rid_str = f"rIdFnt{next_rid_num}"
            next_rid_num += 1

            # Relationship
            rel_xml = (
                f'<Relationship Id="{rid_str}" '
                f'Type="{FONT_REL_TYPE}" '
                f'Target="{font_file_name}"/>'
            )
            new_rels_parts.append(rel_xml)

            # Embedded font element
            font_xml = (
                f'<p:embeddedFont>'
                f'<p:font typeface="{font_name}"/>'
                f'<p:regular r:id="{rid_str}"/>'
                f'</p:embeddedFont>'
            )
            embedded_font_xml_parts.append(font_xml)
            font_index += 1

        if not embedded_font_xml_parts:
            return 0

        # Insert new relationships before </Relationships>
        if new_rels_parts:
            rels_str = rels_str.replace("</Relationships>", f"{''.join(new_rels_parts)}</Relationships>")
            file_map["ppt/_rels/presentation.xml.rels"] = rels_str.encode("utf-8")

        # Insert <p:embeddedFontList> into presentation.xml
        font_list_xml = f"<p:embeddedFontList>{''.join(embedded_font_xml_parts)}</p:embeddedFontList>"

        if "<p:embeddedFontList>" in pres_str:
            # Replace existing empty or partial embeddedFontList
            pres_str = re.sub(
                r"<p:embeddedFontList>.*?</p:embeddedFontList>",
                font_list_xml,
                pres_str,
                flags=re.DOTALL,
            )
        else:
            # Insert before </p:presentation>
            pres_str = pres_str.replace("</p:presentation>", f"{font_list_xml}</p:presentation>")

        file_map["ppt/presentation.xml"] = pres_str.encode("utf-8")

        # Write updated package back
        with zipfile.ZipFile(pptx_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name, content in file_map.items():
                zout.writestr(name, content)

        logger.info("Successfully embedded %d fonts into %s", len(extracted_fonts), pptx_path.name)
        return len(extracted_fonts)
    except Exception as exc:
        logger.warning("Could not embed fonts into PPTX: %s", exc)
        return 0

