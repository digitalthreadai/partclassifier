"""
Pattern-based pre-extraction of part attributes from scraped content.

Uses regex patterns built from the ALIASES dict in attr_schema.py to
extract key-value pairs. Always sends results TO the LLM for validation
(never skips LLM). Logs agreement rate for future threshold tuning.

Extracts from:
1. Structured tables (highest reliability)
2. Key-value patterns ("Inner Diameter: 21.2mm")
3. Inline dimensions ("21.2 mm x 33.6 mm")
4. Standards (DIN 127B, ASME B18.21.1)
5. Materials (18-8 Stainless Steel, 304 SS)
"""

import re
from src.attr_schema import ALIASES, get_schema


# ── Value patterns ────────────────────────────────────────────────────────────

# Matches a numeric value with optional unit
_NUM_UNIT = r"([\d./]+(?:\s*[-–to]\s*[\d./]+)?\s*(?:mm|in|inches|\"|\u2033)?)"

# Standards patterns
_STANDARDS_RE = re.compile(
    r"((?:DIN|ASME|ISO|ANSI|JIS|BS|SAE|ASTM|MIL)\s*[A-Z]?\s*[\d.]+(?:[-/][A-Z0-9.]+)*)",
    re.IGNORECASE,
)

# Material patterns
_MATERIAL_RE = re.compile(
    r"(18-8\s+Stainless\s+Steel|304\s*(?:L)?\s*(?:Stainless\s+Steel|SS)"
    r"|316\s*(?:L)?\s*(?:Stainless\s+Steel|SS)"
    r"|A2[-\s]*(?:Stainless\s+Steel|SS)|A4[-\s]*(?:Stainless\s+Steel|SS)"
    r"|Carbon\s+Steel|Alloy\s+Steel|Zinc(?:\s+Plated)?"
    r"|Brass|Nylon|Nitrile|Buna[-\s]*N|NBR|Viton|FKM|EPDM|Silicone"
    r"|PTFE|Teflon|Ceramic|Titanium|Aluminum|Copper"
    r"|Grade\s+[258]\d*|Class\s+\d+\.?\d*"
    r"|400\s+Series\s+Stainless\s+Steel"
    r"|(?:17-4\s+PH|15-5\s+PH)\s*(?:Stainless\s+Steel)?)",
    re.IGNORECASE,
)

# Build label patterns from ALIASES
def _build_label_patterns() -> dict[str, re.Pattern]:
    """Build regex patterns for each canonical attribute from ALIASES."""
    # Group aliases by canonical name
    canonical_to_aliases: dict[str, list[str]] = {}
    for alias, canonical in ALIASES.items():
        if canonical not in canonical_to_aliases:
            canonical_to_aliases[canonical] = []
        canonical_to_aliases[canonical].append(alias)

    patterns: dict[str, re.Pattern] = {}
    for canonical, aliases in canonical_to_aliases.items():
        # Skip non-dimensional attributes (handled by specific patterns)
        if canonical in ("RoHS", "REACH", "Performance"):
            continue
        # Escape and join aliases
        escaped = [re.escape(a) for a in aliases]
        label_group = "|".join(escaped)
        # Match: Label [separator] Value
        pattern = re.compile(
            rf"(?:{label_group})\s*[:=]\s*(.+?)(?:\n|$)",
            re.IGNORECASE | re.MULTILINE,
        )
        patterns[canonical] = pattern

    return patterns


_LABEL_PATTERNS = _build_label_patterns()


# ── Main extraction function ──────────────────────────────────────────────────

def regex_extract(
    text: str,
    part_class: str,
    tables: list[dict] | None = None,
) -> dict[str, str]:
    """Extract attributes from text and/or tables using pattern matching.

    Args:
        text: Cleaned text content from web scrape.
        part_class: The classified part type (for schema-aware extraction).
        tables: Optional list of {header: value} dicts from HTML tables.

    Returns:
        Dict of {canonical_attr_name: value} for attributes found.
    """
    extracted: dict[str, str] = {}

    # 1. Table extraction (highest reliability)
    if tables:
        extracted.update(_extract_from_tables(tables))

    # 2. Key-value label patterns
    for canonical, pattern in _LABEL_PATTERNS.items():
        if canonical in extracted:
            continue  # Table value takes priority
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            # Clean up: remove trailing punctuation, limit length
            value = value.rstrip(".,;:").strip()
            if value and len(value) < 80:
                extracted[canonical] = value

    # 3. Standards extraction
    if "Standard" not in extracted:
        std_match = _STANDARDS_RE.search(text)
        if std_match:
            extracted["Standard"] = std_match.group(1).strip()

    # 4. Material extraction
    if "Material" not in extracted:
        mat_match = _MATERIAL_RE.search(text)
        if mat_match:
            extracted["Material"] = mat_match.group(1).strip()

    return extracted


def _extract_from_tables(tables: list[dict]) -> dict[str, str]:
    """Match table headers against ALIASES to extract canonical attributes."""
    extracted: dict[str, str] = {}

    for table in tables:
        for header, value in table.items():
            header_lower = header.lower().strip().rstrip(":")
            # Direct alias match
            if header_lower in ALIASES:
                canonical = ALIASES[header_lower]
                if canonical not in extracted:
                    extracted[canonical] = str(value).strip()

    return extracted


# ── Agreement tracking ────────────────────────────────────────────────────────

def compute_agreement(regex_attrs: dict, llm_attrs: dict) -> dict:
    """Compare regex-extracted vs LLM-extracted attributes.

    Returns metrics dict for logging:
    - regex_count: how many attrs regex found
    - llm_count: how many attrs LLM found
    - agreed: how many shared keys have same value
    - disagreed: how many shared keys have different values
    - regex_only: keys regex found but LLM didn't
    - llm_only: keys LLM found but regex didn't
    """
    regex_keys = set(regex_attrs.keys())
    llm_keys = set(llm_attrs.keys())
    shared = regex_keys & llm_keys

    agreed = 0
    disagreed = 0
    for key in shared:
        if regex_attrs[key].strip().lower() == llm_attrs[key].strip().lower():
            agreed += 1
        else:
            disagreed += 1

    return {
        "regex_count": len(regex_keys),
        "llm_count": len(llm_keys),
        "agreed": agreed,
        "disagreed": disagreed,
        "regex_only": len(regex_keys - llm_keys),
        "llm_only": len(llm_keys - regex_keys),
    }
