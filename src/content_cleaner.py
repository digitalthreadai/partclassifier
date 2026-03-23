"""
Table-aware content extraction from HTML.

Extracts HTML tables as structured key-value data, then combines with
cleaned body text. Tables are prioritized over narrative because
distributor sites present specs in tabular form.

Uses BeautifulSoup only (no extra dependencies).
"""

import re
from dataclasses import dataclass, field
from bs4 import BeautifulSoup


# Keywords that indicate a table contains spec data
SPEC_TABLE_KEYWORDS = {
    "diameter", "thickness", "material", "hardness", "standard",
    "dimension", "bore", "width", "height", "length", "weight",
    "thread", "pitch", "grade", "finish", "pressure", "temperature",
    "voltage", "current", "power", "size", "type", "series",
    "specification", "parameter", "value", "property", "feature",
    "od", "id", "oal", "metric", "imperial", "inch", "mm",
}

MAX_TABLE_CHARS = 3000
MAX_TEXT_CHARS = 5000
MAX_COMBINED_CHARS = 8000


@dataclass
class ContentResult:
    """Result of content extraction from HTML."""
    tables: list[dict] = field(default_factory=list)  # [{header: value}, ...]
    clean_text: str = ""       # BS4 cleaned text (nav/footer removed)
    combined: str = ""         # tables + clean_text merged for LLM consumption
    table_text: str = ""       # tables formatted as "Label: Value" lines


def extract_content(html: str, url: str = "") -> ContentResult:
    """Extract structured tables + clean text from raw HTML.

    Returns ContentResult with tables prioritized in combined output
    so specs are never cut off by navigation boilerplate.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract spec tables BEFORE stripping tags
    tables = _extract_tables(soup)
    table_text = _format_tables(tables)

    # 2. Clean text (remove non-content elements)
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                      "aside", "iframe", "form"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 3. Combine: tables first (most reliable), then narrative
    parts = []
    if table_text:
        parts.append(table_text[:MAX_TABLE_CHARS])
    if text:
        parts.append(text[:MAX_TEXT_CHARS])

    combined = "\n\n".join(parts)
    if len(combined) > MAX_COMBINED_CHARS:
        combined = combined[:MAX_COMBINED_CHARS]

    return ContentResult(
        tables=tables,
        clean_text=text[:MAX_TEXT_CHARS] if text else "",
        combined=combined,
        table_text=table_text,
    )


def _extract_tables(soup: BeautifulSoup) -> list[dict]:
    """Extract HTML tables as list of {header: value} dicts.

    Handles two common patterns:
    1. Header row + data rows: <th>Material</th> ... <td>Stainless Steel</td>
    2. Two-column label-value: <td>Material</td><td>Stainless Steel</td>
    """
    all_tables: list[dict] = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Try pattern 1: header row with <th> elements
        headers = [th.get_text(strip=True) for th in rows[0].find_all(["th"])]
        if headers and len(headers) >= 2:
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cells) >= len(headers):
                    row_dict = {}
                    for h, c in zip(headers, cells):
                        if h and c:
                            row_dict[h] = c
                    if row_dict and _is_spec_table(row_dict):
                        all_tables.append(row_dict)
            continue

        # Try pattern 2: two-column label-value pairs
        table_dict: dict[str, str] = {}
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) == 2 and cells[0] and cells[1]:
                # First cell is label, second is value
                label = cells[0].rstrip(":").strip()
                value = cells[1].strip()
                if label and value and len(label) < 60:
                    table_dict[label] = value

        if len(table_dict) >= 2 and _is_spec_table(table_dict):
            all_tables.append(table_dict)

    return all_tables


def _is_spec_table(row_dict: dict) -> bool:
    """Check if a table row/dict likely contains spec data."""
    text = " ".join(list(row_dict.keys()) + list(row_dict.values())).lower()
    matches = sum(1 for kw in SPEC_TABLE_KEYWORDS if kw in text)
    return matches >= 2


def _format_tables(tables: list[dict]) -> str:
    """Format extracted tables as 'Label: Value' lines for LLM consumption."""
    lines: list[str] = []
    seen_keys: set[str] = set()

    for table in tables:
        for key, value in table.items():
            # Deduplicate across tables
            key_lower = key.lower().strip()
            if key_lower in seen_keys:
                continue
            seen_keys.add(key_lower)
            lines.append(f"{key}: {value}")

    return "\n".join(lines)
