"""
Read parts from the input Excel file.
Write one output Excel file per part class into the output/ folder.
"""

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from pathlib import Path
from typing import Any

INPUT_COLUMNS = [
    "Part Number",
    "Part Name",
    "Manufacturer Part Number",
    "Manufacturer Name",
    "Unit of Measure",
]

# Fuzzy aliases for input column headers — handles different naming conventions
COLUMN_ALIASES = {
    "Part Number": ["PN", "Internal PN", "Item Number", "Item No", "Part No", "Part #"],
    "Part Name": ["Description", "Part Description", "Name", "Item Name", "Item Description"],
    "Manufacturer Part Number": ["Mfg Part Number", "MFG PN", "Mfg PN", "MPN",
                                  "Manufacturer PN", "Mfg Part No", "Mfr Part Number",
                                  "Mfr PN", "Vendor Part Number", "Vendor PN"],
    "Manufacturer Name": ["Mfg Name", "MFG Name", "Manufacturer", "Mfg", "Mfr Name",
                           "Mfr", "Vendor Name", "Vendor", "Supplier", "Supplier Name"],
    "Unit of Measure": ["UOM", "Unit", "Units", "Measure"],
}

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
CENTER = Alignment(horizontal="center", wrap_text=True)

# Result columns written before the dynamic attribute columns
RESULT_PREFIX_COLS = ["Part Class", "TC Class ID", "Source URL"]


class ExcelHandler:
    def __init__(self, input_path: str, output_dir: str):
        self.input_path = input_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def read_parts(self) -> list[dict[str, Any]]:
        """Return list of dicts keyed by INPUT_COLUMNS header names.

        Uses fuzzy column matching: tries exact match, then aliases,
        then case-insensitive match. Prints matched columns for debugging.
        """
        wb = openpyxl.load_workbook(self.input_path)
        ws = wb.active
        raw_headers = [cell.value for cell in ws[1]]
        # Strip whitespace from headers
        headers = [str(h).strip() if h else "" for h in raw_headers]
        headers_lower = [h.lower() for h in headers]

        input_indices: dict[str, int] = {}
        for col in INPUT_COLUMNS:
            # Try exact match first
            if col in headers:
                input_indices[col] = headers.index(col)
                continue
            # Try aliases
            matched = False
            for alias in COLUMN_ALIASES.get(col, []):
                if alias in headers:
                    input_indices[col] = headers.index(alias)
                    print(f"  Column matched: '{alias}' -> '{col}'")
                    matched = True
                    break
            if matched:
                continue
            # Try case-insensitive match
            col_lower = col.lower()
            for i, h in enumerate(headers_lower):
                if h == col_lower:
                    input_indices[col] = i
                    print(f"  Column matched (case-insensitive): '{headers[i]}' -> '{col}'")
                    break
            # Try case-insensitive alias match
            if col not in input_indices:
                for alias in COLUMN_ALIASES.get(col, []):
                    alias_lower = alias.lower()
                    for i, h in enumerate(headers_lower):
                        if h == alias_lower:
                            input_indices[col] = i
                            print(f"  Column matched (alias): '{headers[i]}' -> '{col}'")
                            break
                    if col in input_indices:
                        break

        if not input_indices:
            print(f"  WARNING: No matching columns found. Headers: {headers}")

        parts = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            part = {col: row[idx] for col, idx in input_indices.items()}
            parts.append(part)
        return parts

    def write_class_files(self, results: list[dict]) -> list[str]:
        """
        Group results by part_class and write one Excel per class.
        Each result dict must have keys: part (input dict), part_class, attributes, source_url.
        Returns list of output file paths written.
        """
        # Group by class
        by_class: dict[str, list[dict]] = {}
        for r in results:
            cls = r.get("part_class") or "Unclassified"
            by_class.setdefault(cls, []).append(r)

        written = []
        for cls, class_results in by_class.items():
            path = self._write_one_class(cls, class_results)
            written.append(path)
        return written

    # ── Private ───────────────────────────────────────────────────────────────

    def _write_one_class(self, cls: str, results: list[dict]) -> str:
        """Write a single per-class Excel file. Returns the file path."""
        # Collect all unique attribute keys across every part in this class
        all_attr_keys: list[str] = []
        seen: set[str] = set()
        for r in results:
            for k in r.get("attributes", {}).keys():
                if k not in seen:
                    all_attr_keys.append(k)
                    seen.add(k)

        # Build full column list
        all_columns = INPUT_COLUMNS + RESULT_PREFIX_COLS + all_attr_keys

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = cls[:31]  # Excel sheet name limit

        # Write headers
        for col_idx, header in enumerate(all_columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = CENTER

        # Write data rows
        for row_idx, r in enumerate(results, start=2):
            part = r.get("part", {})
            attrs = r.get("attributes", {})

            # Input columns
            for col_idx, col_name in enumerate(INPUT_COLUMNS, start=1):
                ws.cell(row=row_idx, column=col_idx, value=part.get(col_name))

            # Result prefix columns: Part Class, TC Class ID, Source URL
            offset = len(INPUT_COLUMNS) + 1
            ws.cell(row=row_idx, column=offset, value=r.get("part_class", ""))
            ws.cell(row=row_idx, column=offset + 1, value=r.get("tc_class_id", ""))
            ws.cell(row=row_idx, column=offset + 2, value=str(r.get("source_url", "")))

            # Attribute columns
            attr_offset = offset + len(RESULT_PREFIX_COLS)
            for i, key in enumerate(all_attr_keys):
                ws.cell(row=row_idx, column=attr_offset + i, value=attrs.get(key, ""))

        # Auto-size columns
        for col in ws.columns:
            max_len = max(
                (len(str(cell.value)) for cell in col if cell.value),
                default=10,
            )
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 45)

        # Safe filename (strip characters invalid in file names)
        import re
        safe_cls = re.sub(r'[\\/:*?"<>|]', "_", cls)
        out_path = self.output_dir / f"{safe_cls}.xlsx"
        wb.save(str(out_path))
        return str(out_path)
