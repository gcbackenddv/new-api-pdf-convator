from __future__ import annotations

import json
from pathlib import Path

from app.services.pdf_extract_tables.exporters.base import ExportedFile
from app.services.pdf_extract_tables.models import TableDocument


class JSONExporter:
    def export(self, document: TableDocument, output_dir: Path) -> list[ExportedFile]:
        path = output_dir / "extracted-tables.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(document.to_dict(), fh, ensure_ascii=False, indent=2)   # real UTF-8, not \u escapes
        return [ExportedFile(path, path.name, "application/json", inline=True)]