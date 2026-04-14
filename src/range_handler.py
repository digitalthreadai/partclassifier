"""
Range value parsing and averaging for numeric attributes.

When LLM extracts a range like "3.8 mm to 4.2 mm" or "0.5-1.0 in", and the
attribute is declared as a numeric type (float/double/int) in Attributes.json,
this module computes the average value (4.0 mm in the example).

For string-typed attributes or unknown types, ranges are preserved as-is unless
the value is purely numeric (auto-detect fallback).
"""

import json
import re
from pathlib import Path

# Match: <num> [unit?] [to|-|–|—] <num> [unit?]
# Allows:
#   "3.8 mm to 4.2 mm"
#   "3.8 to 4.2 mm"
#   "3.8-4.2 mm"
#   "0.5–1.0 in"
#   "3.8 to 4.2"
_RANGE_RE = re.compile(
    r"^\s*([+-]?\d+\.?\d*)\s*([a-zA-Z%\"\u2032\u2033]*)\s*"
    r"(?:to|-|\u2013|\u2014)\s*"
    r"([+-]?\d+\.?\d*)\s*([a-zA-Z%\"\u2032\u2033]*)\s*$"
)

# Match: <nominal value + optional unit> followed by +/- or ± and a tolerance amount
_TOLERANCE_RE = re.compile(r'^(.+?)\s*(?:\+/-|±)\s*\d', re.IGNORECASE)

# ── Type behavior config (loaded from schema/attr_type_rules.json) ────────────

_TYPE_RULES_PATH = Path(__file__).parent.parent / "schema" / "attr_type_rules.json"


def _load_type_rules() -> dict:
    try:
        with open(_TYPE_RULES_PATH, "r", encoding="utf-8") as f:
            rules = json.load(f)
        # Validate: every listed type should have a behavior entry
        behaviors = rules.get("type_behaviors", {})
        for t in rules.get("numeric_types", []) + rules.get("string_types", []):
            if t not in behaviors:
                print(f"[AttrTypeRules] WARNING: type '{t}' has no entry in type_behaviors")
        return rules
    except Exception as e:
        print(f"[AttrTypeRules] WARNING: failed to load attr_type_rules.json: {e}. Using defaults.")
        return {
            "version": 0,
            "numeric_types": ["float", "double", "int", "integer", "number", "numeric", "real"],
            "string_types": ["string", "text", "char", "varchar", "str", "lov"],
            "type_behaviors": {},
        }


_TYPE_RULES = _load_type_rules()
_NUMERIC_TYPES: frozenset[str] = frozenset(t.lower() for t in _TYPE_RULES.get("numeric_types", []))
_STRING_TYPES: frozenset[str] = frozenset(t.lower() for t in _TYPE_RULES.get("string_types", []))


def strip_tolerance(value: str) -> str:
    """Strip tolerance suffix from a numeric value, keeping only the nominal.

    Examples:
        "0.062 in +/- 0.007 in"  →  "0.062 in"
        "5mm ± 0.5mm"            →  "5mm"
        "0.062 +/- 0.007"        →  "0.062"
    """
    stripped = value.strip()
    m = _TOLERANCE_RE.match(stripped)
    if m:
        return m.group(1).rstrip()
    return value


# ── Fraction → decimal ───────────────────────────────────────────────────────
# Mixed number: "1-1/2" or "2 3/4". Whole separated from fraction by space or hyphen.
# Guard: not preceded by digit/decimal (avoid catching "1.5-1/2").
_MIXED_FRAC_RE = re.compile(r"(?<![\d.])(\d+)[\s-](\d+)\s*/\s*(\d+)(?!\s*/\s*\d)")

# Plain fraction: "13/64", "1/4". Guard against dates ("1/1/2024") and version
# strings by requiring no digit/decimal before and no extra "/digit" after.
_PLAIN_FRAC_RE = re.compile(r"(?<![\d./])(\d+)\s*/\s*(\d+)(?!\s*/?\s*\d)")


def _fmt_decimal(val: float) -> str:
    """3-decimal-place format with trailing zeros stripped."""
    s = f"{val:.3f}".rstrip("0").rstrip(".")
    return s or "0"


def fraction_to_decimal(value: str) -> str:
    """Replace plain and mixed fractions in `value` with decimal equivalents.

    "13/64\""        -> "0.203\""
    "1/4 in"         -> "0.25 in"
    "1-1/2\""        -> "1.5\""
    "2 3/4\""        -> "2.75\""
    "1/2 to 3/4 in"  -> "0.5 to 0.75 in"
    "3.8 to 4.2 mm"  -> unchanged
    "1/1/2024"       -> unchanged (date guard)
    """
    if not value or "/" not in value:
        return value

    # Mixed numbers first ("1-1/2" → "1.5"), so the fraction half isn't double-matched.
    def _mixed_sub(m: re.Match) -> str:
        whole = int(m.group(1))
        num = int(m.group(2))
        denom = int(m.group(3))
        if denom == 0:
            return m.group(0)
        return _fmt_decimal(whole + num / denom)

    out = _MIXED_FRAC_RE.sub(_mixed_sub, value)

    def _plain_sub(m: re.Match) -> str:
        num = int(m.group(1))
        denom = int(m.group(2))
        if denom == 0:
            return m.group(0)
        return _fmt_decimal(num / denom)

    out = _PLAIN_FRAC_RE.sub(_plain_sub, out)
    return out


# ── Unit suffix stripping ────────────────────────────────────────────────────
# UOM is captured in a separate Excel column, so attribute *values* should not
# repeat the unit. We strip only when the value is unambiguously "<number><unit>".

# Trailing unit token at end of value: 21.2 mm  /  0.5 in  /  0.203"  /  4.2 MM
_TRAILING_UNIT_RE = re.compile(
    r"^\s*([+-]?\d+\.?\d*)\s*"
    r"(?:mm|millimeters?|in|inch|inches|\"|\u2032|\u2033)\s*$",
    re.IGNORECASE,
)

# Range with units: "0.5 to 0.75 in" / "3.8 mm to 4.2 mm" / "0.5\" to 0.75\""
_RANGE_UNIT_RE = re.compile(
    r"^\s*([+-]?\d+\.?\d*)\s*(?:mm|millimeters?|in|inch|inches|\"|\u2032|\u2033)?\s*"
    r"(to|-|\u2013|\u2014)\s*"
    r"([+-]?\d+\.?\d*)\s*(?:mm|millimeters?|in|inch|inches|\"|\u2032|\u2033)\s*$",
    re.IGNORECASE,
)


def strip_unit_suffix(value: str, datatype: str | None = None) -> str:
    """Strip trailing length-unit tokens from numeric values.

    Examples:
      "21.2 mm"        -> "21.2"
      '0.203"'         -> "0.203"
      "0.5 in"         -> "0.5"
      "3.8 to 4.2 mm"  -> "3.8 to 4.2"
      "Stainless Steel"-> unchanged
      "M20"            -> unchanged (no leading numeric/unit pair)
      "Rockwell C34"   -> unchanged

    Strips for explicit numeric datatypes always; for unknown datatype only
    when the value matches "<num><unit>" or "<num><unit?> to <num><unit>"
    cleanly. Never strips for explicit string datatypes.
    """
    if not value or not isinstance(value, str):
        return value
    is_num = is_numeric_datatype(datatype)
    if is_num is False:
        return value

    m = _TRAILING_UNIT_RE.match(value)
    if m:
        return m.group(1)

    m = _RANGE_UNIT_RE.match(value)
    if m:
        sep = m.group(2)
        # Normalize the separator with single spaces
        return f"{m.group(1)} {sep} {m.group(3)}"

    return value


def is_numeric_datatype(datatype: str | None) -> bool | None:
    """Returns True if numeric, False if string, None if unknown/missing."""
    if not datatype:
        return None
    dt = datatype.strip().lower()
    if dt in _NUMERIC_TYPES:
        return True
    if dt in _STRING_TYPES:
        return False
    return None


def parse_range(value: str) -> tuple[float, float, str] | None:
    """Parse a range string. Returns (low, high, unit) or None if not a range."""
    if not value or not isinstance(value, str):
        return None
    # Fast-path: skip the regex if the value contains no range separator
    if "to" not in value and "-" not in value and "\u2013" not in value and "\u2014" not in value:
        return None
    m = _RANGE_RE.match(value.strip())
    if not m:
        return None
    try:
        low = float(m.group(1))
        high = float(m.group(3))
    except (ValueError, TypeError):
        return None
    # Prefer trailing unit, fall back to leading
    unit = (m.group(4) or m.group(2) or "").strip()
    return (low, high, unit)


def get_type_behavior(type_name: str) -> dict:
    """Return behavior config dict for the given type name from attr_type_rules.json.

    Returns empty dict for unknown types — callers treat missing keys as False.
    """
    return _TYPE_RULES.get("type_behaviors", {}).get((type_name or "").lower(), {})


def apply_precision(value: str, precision: int) -> str:
    """Round a numeric string to given decimal places using Decimal ROUND_HALF_UP.

    Requires that unit suffixes have already been stripped (strip_unit_suffix).
    Non-numeric values returned unchanged. precision must be >= 0.
    """
    precision = int(precision)
    if precision < 0 or not value:
        return value
    try:
        from decimal import Decimal, ROUND_HALF_UP
        d = Decimal(value)
        # Count existing decimal places; only round if value exceeds precision — never pad
        existing = max(0, -d.as_tuple().exponent)
        if existing <= precision:
            return value
        quantizer = Decimal(10) ** -precision
        return str(d.quantize(quantizer, rounding=ROUND_HALF_UP))
    except Exception:
        return value  # not a plain number — leave unchanged


def apply_length(value: str, length: int, type_name: str) -> tuple[str, str | None]:
    """Enforce max length constraint.

    For string types: truncate to `length` characters and return original for audit.
    For numeric types: log a warning but do NOT truncate (numeric length is informational).

    Returns:
        (result_value, original_if_truncated)  — original is None when unchanged.
    """
    if not value:
        return value, None
    _length = int(length)
    type_lower = (type_name or "").lower()
    if type_lower in _STRING_TYPES:
        if len(value) > _length:
            print(f"[AttrType] String value truncated to length {_length}: '{value[:40]}...'")
            return value[:_length], value
    else:
        integer_part = str(value).split(".")[0].lstrip("-+")
        integer_digit_count = len(integer_part)
        if integer_digit_count > _length:
            print(f"[AttrType] WARNING: numeric value '{value}' has {integer_digit_count} integer digits, "
                  f"exceeds declared length {_length} — not truncated")
    return value, None


def apply_sign(value: str, sign: int) -> bool:
    """Check sign constraint for integer attributes.

    sign=0 → value must be non-negative (>= 0).
    sign=1 → value must be non-positive (<= 0).

    Returns True if constraint satisfied (or value is non-numeric), False if violated.
    Violated values should be DROPPED by the caller, not silently modified.
    """
    try:
        n = float(value)
        _sign = int(sign)
        if _sign == 0 and n < 0:
            return False  # positive required, negative found → violated
        if _sign == 1 and n > 0:
            return False  # negative required, positive found → violated
        return True
    except (ValueError, TypeError):
        return True  # non-numeric: not applicable, don't drop


def average_range(value: str, datatype: str | None = None) -> str:
    """If `value` is a numeric range AND attribute is numeric, return the average.

    Logic:
      datatype = "float"/"int"/etc.  -> always average if range
      datatype = "string"/"text"     -> never touch (return as-is)
      datatype = None                -> auto-detect: average if range parses
                                        as pure numbers; otherwise leave as-is
    """
    is_num = is_numeric_datatype(datatype)
    if is_num is False:
        return value  # explicit string type — never average

    parsed = parse_range(value)
    if not parsed:
        return value  # not a range, no change

    low, high, unit = parsed
    avg = (low + high) / 2

    # Format average: preserve precision of inputs
    if low == int(low) and high == int(high):
        avg_str = str(int(round(avg)))
    else:
        precision = max(
            len(str(low).split(".")[-1]) if "." in str(low) else 0,
            len(str(high).split(".")[-1]) if "." in str(high) else 0,
        )
        avg_str = f"{avg:.{precision}f}"

    return f"{avg_str} {unit}".strip() if unit else avg_str
