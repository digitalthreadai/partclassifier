"""Parse Part Name into dimensional signals and validate web content against them.

Part names in this system are structured spec strings containing real ground-truth
values from the user's own data. Examples:
  WSHT, #5, INTL TOOTH,.136ID,.280OD,.017T
  WSHR, SPT LK, M20, 21.2 MM ID, 33.6 MM O
  WASHER, FLAT, #10, 13/64"ID X 1"OD, SS

If a scraped web page contains none of those values, it is the wrong page.
"""

import re

# decimal/fraction BEFORE ID/OD/T/THICKNESS, optional unit between
# matches: .136ID  0.280OD  .017T  21.2 MM ID  13/64"ID
DIM_RE = re.compile(
    r'((?:\d+/\d+|\d*\.\d+|\d+))\s*(?:MM|IN|INCH|"|\')?\s*(ID|OD|T(?:HICKNESS)?)\b',
    re.IGNORECASE,
)

# metric thread: M20, M8, M12, M3.5
METRIC_RE = re.compile(r'\bM(\d+(?:\.\d+)?)\b')

# unified size: #5, #10, #8
UNIFIED_RE = re.compile(r'#(\d+)\b')

# trailing OD shorthand: "33.6 MM O" (truncated "OD")
TRAILING_O_RE = re.compile(r'(\d+(?:\.\d+)?)\s*MM\s+O\b', re.IGNORECASE)

# rough material code map (kept conservative)
_MATERIAL_HINTS = {
    "SS": "stainless",
    "STST": "stainless",
    "AL": "aluminum",
    "BR": "brass",
    "CU": "copper",
    "TI": "titanium",
}


def _to_decimal(token: str) -> str | None:
    """Convert a numeric token (decimal or fraction) to a normalized decimal string."""
    token = token.strip()
    if not token:
        return None
    try:
        if "/" in token:
            num, denom = token.split("/", 1)
            val = float(num) / float(denom)
        else:
            val = float(token)
    except (ValueError, ZeroDivisionError):
        return None
    # Normalize to up to 3 decimal places, strip trailing zeros
    s = f"{val:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def parse_part_name_signals(part_name: str) -> dict:
    """Extract dimensional signals from a structured part name string.

    Returns:
        {
          "dimensions": ["0.136", "0.28", "0.017"],   # numeric strings
          "sizes":      ["M20", "#5"],                # thread/unified sizes
          "materials":  ["stainless"],                # rough hints
        }
    """
    if not part_name:
        return {"dimensions": [], "sizes": [], "materials": []}

    name = part_name.strip()
    dims: list[str] = []
    sizes: list[str] = []
    materials: list[str] = []
    seen_dims: set[str] = set()

    # ID/OD/T dimensions
    for m in DIM_RE.finditer(name):
        dec = _to_decimal(m.group(1))
        if dec and dec not in seen_dims:
            dims.append(dec)
            seen_dims.add(dec)

    # Trailing "MM O" (truncated OD)
    for m in TRAILING_O_RE.finditer(name):
        dec = _to_decimal(m.group(1))
        if dec and dec not in seen_dims:
            dims.append(dec)
            seen_dims.add(dec)

    # Metric thread sizes (also preserved as searchable signal)
    seen_sizes: set[str] = set()
    for m in METRIC_RE.finditer(name):
        token = f"M{m.group(1)}"
        if token not in seen_sizes:
            sizes.append(token)
            seen_sizes.add(token)

    # Unified sizes
    for m in UNIFIED_RE.finditer(name):
        token = f"#{m.group(1)}"
        if token not in seen_sizes:
            sizes.append(token)
            seen_sizes.add(token)

    # Material hints (whole-word match against uppercase tokens)
    upper_tokens = re.findall(r"\b[A-Z]{2,5}\b", name.upper())
    seen_mat: set[str] = set()
    for tok in upper_tokens:
        hint = _MATERIAL_HINTS.get(tok)
        if hint and hint not in seen_mat:
            materials.append(hint)
            seen_mat.add(hint)

    return {"dimensions": dims, "sizes": sizes, "materials": materials}


# Imperial cue patterns (used by infer_uom_from_part_name)
_INCH_MARK_RE = re.compile(r'\d\s*"')                            # 1" or 13/64"
_INCH_WORD_RE = re.compile(r'\b(IN|INCH|INCHES|IMPERIAL)\b')
_MM_WORD_RE = re.compile(r'\b(MM|METRIC)\b')


def infer_uom_from_part_name(part_name: str) -> str:
    """Infer 'mm' or 'inches' from a part name. Returns '' when unclear.

    Metric votes:  M\\d+ thread, 'MM' token, 'METRIC' word
    Imperial votes: '"' inch mark, 'IN'/'INCH'/'INCHES'/'IMPERIAL' word, '#N' unified size
    Conflict (both > 0) or no signals → return '' (do not guess).
    """
    if not part_name:
        return ""
    name_upper = part_name.upper()

    metric = 0
    imperial = 0

    if _MM_WORD_RE.search(name_upper):
        metric += 1
    if METRIC_RE.search(name_upper):  # M20, M8, ...
        metric += 1

    if _INCH_MARK_RE.search(part_name):
        imperial += 1
    if _INCH_WORD_RE.search(name_upper):
        imperial += 1
    if UNIFIED_RE.search(part_name):  # #5, #10, ...
        imperial += 1

    if metric > 0 and imperial == 0:
        return "mm"
    if imperial > 0 and metric == 0:
        return "inches"
    return ""


def _dim_variants(dec: str) -> list[str]:
    """Generate substring variants of a decimal value to search for in content.

    "0.136" → ["0.136", ".136"]
    "21.2"  → ["21.2"]
    "1"     → ["1"]
    """
    variants = [dec]
    if dec.startswith("0.") and len(dec) > 2:
        variants.append(dec[1:])  # ".136"
    return variants


def validate_web_content(signals: dict, content: str) -> bool:
    """Return True if the content appears relevant to the part.

    Logic:
    - If no dimensions in signals → cannot validate, return True (don't falsely reject)
    - If at least ONE dimension value appears in content → True
    - Otherwise → False (page is wrong)
    """
    if not signals or not content:
        return True
    dims = signals.get("dimensions") or []
    if not dims:
        return True

    text = content
    for dec in dims:
        for variant in _dim_variants(dec):
            if variant in text:
                return True
    return False
