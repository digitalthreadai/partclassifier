"""
Range value parsing and averaging for numeric attributes.

When LLM extracts a range like "3.8 mm to 4.2 mm" or "0.5-1.0 in", and the
attribute is declared as a numeric type (float/double/int) in Attributes.json,
this module computes the average value (4.0 mm in the example).

For string-typed attributes or unknown types, ranges are preserved as-is unless
the value is purely numeric (auto-detect fallback).
"""

import re

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

_NUMERIC_TYPES = {"float", "double", "int", "integer", "number", "numeric", "real"}
_STRING_TYPES = {"string", "text", "char", "varchar", "str"}


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
