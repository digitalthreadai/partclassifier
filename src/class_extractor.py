"""
Extract Part Class from scraped manufacturer website content — no LLM needed.

Scans breadcrumbs, category labels, page titles, URL paths, and keyword density
to deterministically match against KNOWN_CLASSES. Returns None if no confident
match found, signaling the caller to fall back to LLM classification.
"""

import re
import urllib.parse
from src.attr_schema import KNOWN_CLASSES, CLASS_ALIASES, CLASS_TREE_CHILDREN


# Parent → child relationships loaded from JSON via attr_schema
_PARENT_CHILDREN = CLASS_TREE_CHILDREN

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


def extract_class_from_content(
    content: str,
    source_url: str = "",
    mfg_name: str = "",
    mfg_part_num: str = "",
) -> str | None:
    """Extract part class from scraped web content using pattern matching.

    Returns a KNOWN_CLASSES name if found with sufficient confidence, or None.
    If mfg_name/mfg_part_num are provided, verifies the content is actually
    about the right part before trusting the classification.
    """
    if not content or len(content) < 50:
        return None

    # Source relevance check: verify part number appears in content or URL
    # Only checks part number — NOT manufacturer name, because cross-manufacturer
    # distributor sites (e.g., NSK bearing on NTN website) are valid sources
    if mfg_part_num:
        pn_lower = mfg_part_num.lower()
        pn_in_content = pn_lower in content.lower()
        pn_in_url = pn_lower in source_url.lower() if source_url else False
        if not pn_in_content and not pn_in_url:
            # Page doesn't mention this part number at all — wrong page
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
