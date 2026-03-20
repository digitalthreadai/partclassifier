"""
Extract Part Class from scraped manufacturer website content — no LLM needed.

Scans breadcrumbs, category labels, page titles, URL paths, and keyword density
to deterministically match against KNOWN_CLASSES. Returns None if no confident
match found, signaling the caller to fall back to LLM classification.
"""

import re
import urllib.parse
from src.attr_schema import KNOWN_CLASSES


# ── Aliases: abbreviations & common variants → canonical class name ──────────

CLASS_ALIASES: dict[str, str] = {
    # Bearings
    "dgbb": "Deep Groove Ball Bearing",
    "deep groove": "Deep Groove Ball Bearing",
    "radial ball bearing": "Deep Groove Ball Bearing",
    "angular contact": "Angular Contact Bearing",
    "needle roller": "Needle Bearing",
    "crossed roller": "Crossed Roller Bearing",
    # Fasteners
    "shcs": "Socket Head Cap Screw",
    "socket head cap": "Socket Head Cap Screw",
    "socket cap screw": "Socket Head Cap Screw",
    "split lock": "Split Lock Washer",
    "spring lock washer": "Split Lock Washer",
    "internal tooth": "Internal Tooth Lock Washer",
    "external tooth": "External Tooth Lock Washer",
    "fender": "Fender Washer",
    "hex cap screw": "Hex Bolt",
    "hex head bolt": "Hex Bolt",
    "carriage": "Carriage Bolt",
    "wing nut": "Wing Nut",
    "nylon insert": "Lock Nut",
    "nyloc": "Lock Nut",
    "blind rivet": "Blind Rivet",
    "pop rivet": "Blind Rivet",
    "cotter": "Cotter Pin",
    "dowel": "Dowel Pin",
    "roll pin": "Roll Pin",
    "spring pin": "Roll Pin",
    "e-clip": "E-Clip",
    "c-clip": "C-Clip",
    "retaining ring": "Retaining Ring",
    "snap ring": "Retaining Ring",
    "circlip": "Retaining Ring",
    # Seals
    "oring": "O-Ring",
    "o ring": "O-Ring",
    # Fittings
    "tube fitting": "Tube Fitting",
    "compression fitting": "Tube Fitting",
    "vcr fitting": "VCR Fitting",
    "pipe fitting": "Pipe Fitting",
    # Pneumatics
    "solenoid valve": "Solenoid Valve",
    "solenoid": "Solenoid Valve",
    "pneumatic cylinder": "Pneumatic Cylinder",
    "air cylinder": "Pneumatic Cylinder",
    "round cylinder": "Pneumatic Cylinder",
    "compact cylinder": "Pneumatic Cylinder",
    "pneumatic valve": "Pneumatic Valve",
    "flow controller": "Flow Controller",
    "pressure regulator": "Pressure Regulator",
    # Sensors
    "proximity sensor": "Proximity Sensor",
    "inductive sensor": "Proximity Sensor",
    "proximity": "Proximity Sensor",
    "photoelectric sensor": "Photoelectric Sensor",
    "photoelectric": "Photoelectric Sensor",
    "fiber optic sensor": "Fiber Optic Sensor",
    "fiber sensor": "Fiber Optic Sensor",
    "fiber unit": "Fiber Optic Sensor",
    "laser sensor": "Laser Sensor",
    "pressure sensor": "Pressure Sensor",
    "pressure transducer": "Pressure Sensor",
    # Vacuum & Semiconductor
    "vacuum valve": "Vacuum Valve",
    "butterfly valve": "Vacuum Valve",
    "gate valve": "Gate Valve",
    "mass flow controller": "Mass Flow Controller",
    "mfc": "Mass Flow Controller",
    "wafer carrier": "Wafer Carrier",
    "wafer shipper": "Wafer Shipper",
    "foup": "Wafer Carrier",
    "vacuum gauge": "Vacuum Gauge",
    "pressure gauge": "Pressure Gauge",
    # Linear Motion
    "linear guide": "Linear Guide",
    "linear rail": "Linear Guide",
    "linear block": "Linear Block",
    "linear bearing block": "Linear Block",
    "guide block": "Linear Block",
    "ball screw": "Ball Screw",
}

# Parent → child relationships for specificity resolution
_PARENT_CHILDREN: dict[str, list[str]] = {
    "Washer": ["Flat Washer", "Fender Washer", "Lock Washer", "Split Lock Washer",
               "Internal Tooth Lock Washer", "External Tooth Lock Washer"],
    "Lock Washer": ["Split Lock Washer", "Internal Tooth Lock Washer",
                    "External Tooth Lock Washer"],
    "Nut": ["Hex Nut", "Lock Nut", "Wing Nut"],
    "Bolt": ["Hex Bolt", "Carriage Bolt"],
    "Screw": ["Cap Screw", "Set Screw", "Machine Screw", "Socket Head Cap Screw"],
    "Cap Screw": ["Socket Head Cap Screw"],
    "Pin": ["Cotter Pin", "Dowel Pin", "Roll Pin"],
    "Rivet": ["Blind Rivet"],
    "Clip": ["E-Clip", "C-Clip"],
    "Ring": ["Retaining Ring"],
    "Spring": ["Compression Spring"],
    "Ball Bearing": ["Deep Groove Ball Bearing", "Angular Contact Bearing"],
    "Valve": ["Solenoid Valve", "Pneumatic Valve", "Vacuum Valve", "Gate Valve"],
    "Sensor": ["Proximity Sensor", "Photoelectric Sensor", "Fiber Optic Sensor",
               "Laser Sensor", "Pressure Sensor"],
    "Filter": ["Gas Filter", "Liquid Filter"],
    "Fitting": ["Tube Fitting", "VCR Fitting", "Pipe Fitting"],
    "Gauge": ["Pressure Gauge", "Vacuum Gauge"],
}

# Build reverse: child → set of parent classes
_CHILD_PARENTS: dict[str, set[str]] = {}
for parent, children in _PARENT_CHILDREN.items():
    for child in children:
        _CHILD_PARENTS.setdefault(child, set()).add(parent)

# Precompute: KNOWN_CLASSES sorted longest-first for greedy matching
_CLASSES_BY_LENGTH = sorted(KNOWN_CLASSES, key=len, reverse=True)

# Precompute lowercase class names for matching
_CLASS_LOWER = {cls.lower(): cls for cls in KNOWN_CLASSES}

# Breadcrumb separator patterns
_BREADCRUMB_RE = re.compile(
    r"^(.+?(?:\s*[>»/→|]\s*.+?){2,})$",  # at least 3 segments separated by > / » → |
    re.MULTILINE,
)

# Labeled category patterns
_LABEL_RE = re.compile(
    r"(?:product\s*)?(?:type|category|classification)\s*[:：]\s*(.+)",
    re.IGNORECASE,
)


def extract_class_from_content(content: str, source_url: str = "") -> str | None:
    """Extract part class from scraped web content using pattern matching.

    Returns a KNOWN_CLASSES name if found with sufficient confidence, or None.
    """
    if not content or len(content) < 50:
        return None

    head = content[:500].lower()
    full = content.lower()

    # Collect all candidates with scores
    candidates: dict[str, int] = {}

    # 1. Breadcrumb parsing (highest signal)
    _score_breadcrumbs(content[:1000], candidates)

    # 2. Labeled category fields
    _score_labels(content[:2000], candidates)

    # 3. Page title / first line
    _score_title(content, candidates)

    # 4. URL path analysis
    if source_url:
        _score_url(source_url, candidates)

    # 5. Alias matching in head zone
    _score_aliases(head, candidates, zone_score=6)

    # 6. Exact class name matching in head zone
    _score_class_names(head, candidates, zone_score=4)

    # 7. Exact class name matching in full content (lower weight)
    _score_class_names(full, candidates, zone_score=2)

    if not candidates:
        return None

    # Specificity resolution: remove parents when children are present
    _resolve_specificity(candidates)

    # Return highest-scoring class (threshold >= 4)
    best_class = max(candidates, key=candidates.get)
    if candidates[best_class] >= 4:
        return best_class

    return None


# ── Scoring helpers ──────────────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """Lowercase, strip trailing s/es for plural handling."""
    t = text.strip().lower()
    # Remove trailing 's' but not for words like "class" or short words
    if len(t) > 4 and t.endswith("ings"):
        t = t[:-1]  # "bearings" → "bearing", "fittings" → "fitting"
    elif len(t) > 4 and t.endswith("ers"):
        t = t[:-1]  # "washers" → "washer"
    elif len(t) > 4 and t.endswith("es"):
        t = t[:-2]  # "valves" → "valv" — skip this, too aggressive
        t = text.strip().lower()  # revert
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]  # "bolts" → "bolt", "nuts" → "nut"
    return t


def _match_class(text: str) -> str | None:
    """Check if text matches a KNOWN_CLASS (case-insensitive, plural-tolerant)."""
    t = _normalize_text(text)
    if t in _CLASS_LOWER:
        return _CLASS_LOWER[t]
    # Try without hyphens (e.g. "o ring" → "o-ring")
    t_hyphen = t.replace(" ", "-")
    if t_hyphen in _CLASS_LOWER:
        return _CLASS_LOWER[t_hyphen]
    return None


def _score_breadcrumbs(text: str, candidates: dict[str, int]) -> None:
    """Find breadcrumb lines and score class matches within them."""
    for match in _BREADCRUMB_RE.finditer(text):
        line = match.group(1)
        # Split on common breadcrumb separators
        segments = re.split(r"\s*[>»/→|]\s*", line)
        for seg in segments:
            cls = _match_class(seg.strip())
            if cls:
                candidates[cls] = max(candidates.get(cls, 0), 10)
            # Also check aliases
            seg_lower = seg.strip().lower()
            for alias, target in CLASS_ALIASES.items():
                if alias in seg_lower:
                    candidates[target] = max(candidates.get(target, 0), 9)


def _score_labels(text: str, candidates: dict[str, int]) -> None:
    """Find labeled category fields like 'Type: Solenoid Valve'."""
    for match in _LABEL_RE.finditer(text):
        value = match.group(1).strip()
        # Try direct match
        cls = _match_class(value)
        if cls:
            candidates[cls] = max(candidates.get(cls, 0), 9)
            continue
        # Try matching within the value (e.g. "Stainless Steel Tube Fitting")
        value_lower = value.lower()
        for class_name in _CLASSES_BY_LENGTH:
            if class_name.lower() in value_lower:
                candidates[class_name] = max(candidates.get(class_name, 0), 9)
                break


def _score_title(content: str, candidates: dict[str, int]) -> None:
    """Check the first non-empty line (usually page title/H1)."""
    for line in content.split("\n"):
        line = line.strip()
        if line and len(line) > 3:
            title_lower = line.lower()
            for class_name in _CLASSES_BY_LENGTH:
                if class_name.lower() in title_lower:
                    candidates[class_name] = max(candidates.get(class_name, 0), 8)
                    break
            # Also check aliases in title
            for alias, target in CLASS_ALIASES.items():
                if alias in title_lower:
                    candidates[target] = max(candidates.get(target, 0), 7)
            break  # only check first non-empty line


def _score_url(url: str, candidates: dict[str, int]) -> None:
    """Extract class hints from the URL path."""
    try:
        parsed = urllib.parse.urlparse(url)
        path = urllib.parse.unquote(parsed.path).lower()
        host = parsed.netloc.lower()
    except Exception:
        return

    # Domain-specific hints
    domain_hints: dict[str, str] = {
        "lily-bearing": "Ball Bearing",
        "bearingfinder": "Ball Bearing",
        "swagelok": "Tube Fitting",
        "smcworld": "Solenoid Valve",
        "smcpneumatics": "Solenoid Valve",
        "keyence": "Sensor",
        "omron": "Sensor",
    }
    for domain_key, cls in domain_hints.items():
        if domain_key in host:
            candidates[cls] = max(candidates.get(cls, 0), 3)  # low score, just a hint

    # Check path segments for class names
    path_parts = re.split(r"[/\-_]", path)
    path_text = " ".join(path_parts)
    for class_name in _CLASSES_BY_LENGTH:
        cls_lower = class_name.lower().replace("-", " ")
        if cls_lower in path_text:
            candidates[class_name] = max(candidates.get(class_name, 0), 5)

    # Check aliases in path
    for alias, target in CLASS_ALIASES.items():
        if alias.replace(" ", "-") in path or alias.replace(" ", "_") in path:
            candidates[target] = max(candidates.get(target, 0), 4)


def _score_aliases(text: str, candidates: dict[str, int], zone_score: int) -> None:
    """Check for alias matches in text."""
    for alias, target in CLASS_ALIASES.items():
        if alias in text:
            candidates[target] = max(candidates.get(target, 0), zone_score)


def _score_class_names(text: str, candidates: dict[str, int], zone_score: int) -> None:
    """Check for exact class name matches in text (longest-first for specificity)."""
    for class_name in _CLASSES_BY_LENGTH:
        cls_lower = class_name.lower()
        # For single-word classes, require word boundary
        if " " not in cls_lower:
            pattern = r"\b" + re.escape(cls_lower) + r"s?\b"
            if re.search(pattern, text):
                candidates[class_name] = max(candidates.get(class_name, 0), zone_score)
        else:
            # Multi-word: check both exact and plural forms
            if cls_lower in text or cls_lower + "s" in text:
                candidates[class_name] = max(candidates.get(class_name, 0), zone_score)


def _resolve_specificity(candidates: dict[str, int]) -> None:
    """When both parent and child classes match, boost the child and penalize the parent."""
    present = set(candidates.keys())
    for cls in list(present):
        parents = _CHILD_PARENTS.get(cls, set())
        for parent in parents:
            if parent in candidates:
                # Child is present — boost child, penalize parent
                candidates[cls] = max(candidates[cls], candidates[parent] + 1)
                candidates[parent] = max(0, candidates[parent] - 3)
