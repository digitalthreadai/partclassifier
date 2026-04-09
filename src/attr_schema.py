"""
Canonical attribute names and normalization for each part class.

SCHEMA SOURCE
-------------
schema/Classes.json + schema/Attributes.json  (required)
schema/aliases.json                            (optional, loaded last — wins on conflict)

PUBLIC API
----------
- KNOWN_CLASSES: list[str]           — all valid part class names
- TC_CLASS_IDS: dict[str, str]       — class name -> Teamcenter class ID
- CLASS_SCHEMAS: dict[str, list[str]]— class -> ordered canonical attribute names (inherited)
- ALIASES: dict[str, str]            — lowercase alias -> canonical attribute name
- CLASS_ALIASES: dict[str, str]      — lowercase class alias -> canonical class name
- CLASS_TREE_CHILDREN: dict[str, list[str]] — parent class name -> child class names
- CLASS_LOV_MAP: dict[str, dict[str, list[str]]] — class name -> {canonical_attr_name -> [lov_values]}
                                       ID-resolved per class (correct LOV even when attr names clash globally)
- ATTR_DICT: dict[str, dict]         — attr id -> full attribute record
- get_schema(part_class) -> list[str]
- get_tc_class_id(part_class) -> str
- normalize_attrs(raw, part_class) -> dict
- schema_source() -> str
"""

import json
import re
import warnings
from pathlib import Path
from typing import Any


# ── File locations ───────────────────────────────────────────────────────────

_SCHEMA_DIR = Path(__file__).parent.parent / "schema"
_CLASSES_JSON = _SCHEMA_DIR / "Classes.json"
_ATTRS_JSON = _SCHEMA_DIR / "Attributes.json"
_ALIASES_JSON = _SCHEMA_DIR / "aliases.json"


# ── Module-level data (populated at import time) ────────────────────────────

KNOWN_CLASSES: list[str] = []
TC_CLASS_IDS: dict[str, str] = {}          # class_name -> Teamcenter class ID
CLASS_SCHEMAS: dict[str, list[str]] = {}   # class_name -> [canonical attr names] (inherited)
CLASS_LOV_MAP: dict[str, dict[str, list[str]]] = {}  # class_name -> {canonical_attr_name -> [lov_values]}
ALIASES: dict[str, str] = {}               # lowercase alias -> canonical attr name
CLASS_ALIASES: dict[str, str] = {}         # lowercase class alias -> canonical class name
CLASS_TREE_CHILDREN: dict[str, list[str]] = {}  # parent name -> [child names]
ATTR_DICT: dict[str, dict] = {}            # attr id -> full attribute record
ATTR_DATATYPES: dict[str, str] = {}        # canonical attr name -> datatype string (float/string/etc)
_DEFAULT_SCHEMA: list[str] = []
_SCHEMA_SOURCE: str = "none"               # "json" or "none"


# ── JSON loader ──────────────────────────────────────────────────────────────

def _load_from_json(classes_path: Path, attrs_path: Path) -> None:
    """Load schema from Classes.json + Attributes.json."""
    global KNOWN_CLASSES, TC_CLASS_IDS, CLASS_SCHEMAS, CLASS_LOV_MAP, ALIASES, CLASS_ALIASES
    global CLASS_TREE_CHILDREN, ATTR_DICT, _DEFAULT_SCHEMA, _SCHEMA_SOURCE

    # --- Load attributes ---
    with open(attrs_path, "r", encoding="utf-8") as f:
        attrs_data = json.load(f)

    attr_by_id: dict[str, dict] = {}
    attr_name_by_id: dict[str, str] = {}
    attr_lov_by_id: dict[str, list[str]] = {}   # id -> lov_values (for class-scoped lookup)

    for attr in attrs_data.get("attributes", attrs_data.get("tree", [])):
        aid = str(attr["id"])
        attr_by_id[aid] = attr
        attr_name_by_id[aid] = attr["name"]

        # Populate ATTR_DICT
        ATTR_DICT[aid] = attr

        # Populate ALIASES: canonical name + shortname + all aliases
        canonical = attr["name"]
        ALIASES[canonical.lower()] = canonical
        if attr.get("shortname"):
            ALIASES[attr["shortname"].lower()] = canonical
        for alias in attr.get("aliases", []):
            ALIASES[alias.lower()] = canonical

        if attr.get("lov"):
            attr_lov_by_id[aid] = attr["lov"]

        # Populate ATTR_DATATYPES (optional field — supports float/string range averaging)
        if attr.get("datatype"):
            ATTR_DATATYPES[canonical] = attr["datatype"]

    # --- Load classes ---
    with open(classes_path, "r", encoding="utf-8") as f:
        classes_data = json.load(f)

    # Flatten the class tree, computing inherited attributes and class-scoped LOV maps
    _flatten_tree(
        classes_data.get("tree", classes_data.get("classes", [])),
        inherited_attrs=[],
        attr_name_by_id=attr_name_by_id,
        inherited_lov_map={},
        attr_lov_by_id=attr_lov_by_id,
    )

    # Build default schema from common attributes
    _DEFAULT_SCHEMA = [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness", "Length",
        "Width", "Height", "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Performance", "RoHS", "REACH",
    ]

    _SCHEMA_SOURCE = "json"


def _flatten_tree(
    nodes: list[dict],
    inherited_attrs: list[str],
    attr_name_by_id: dict[str, str],
    inherited_lov_map: dict[str, list[str]],
    attr_lov_by_id: dict[str, list[str]],
) -> None:
    """Recursively walk the class tree, populating module-level data.

    Each node accumulates inherited attributes from ancestors plus its own
    directly-assigned attributes. Only leaf and named intermediate classes
    are added to KNOWN_CLASSES.

    CLASS_LOV_MAP is built using attr IDs from attributeslist to resolve the
    CORRECT LOV list for each class — even when multiple attributes share the
    same name globally. First-wins rule: parent LOV takes precedence over
    child re-declarations of the same attribute name.
    """
    for node in nodes:
        name = node["name"]
        class_id = node.get("classid", node.get("classificationId", node.get("id", "")))
        children = node.get("children", [])
        aliases = node.get("aliases", [])

        # Resolve this node's directly-assigned attribute IDs to names
        direct_attr_names = []
        for aid in node.get("attributeslist", []):
            aname = attr_name_by_id.get(str(aid))
            if aname:
                direct_attr_names.append(aname)

        # Full attribute list = inherited + direct (no duplicates, order preserved)
        full_attrs = list(inherited_attrs)
        for a in direct_attr_names:
            if a not in full_attrs:
                full_attrs.append(a)

        # Build class-scoped LOV map: start from inherited (first-wins — parent beats child)
        # Only add LOV for attrs not already in the inherited map (first-wins rule)
        full_lov_map: dict[str, list[str]] = dict(inherited_lov_map)
        for aid in node.get("attributeslist", []):
            aname = attr_name_by_id.get(str(aid))
            if aname and aname not in full_lov_map:
                lov = attr_lov_by_id.get(str(aid))
                if lov:
                    full_lov_map[aname] = lov

        # Register this class
        KNOWN_CLASSES.append(name)
        TC_CLASS_IDS[name] = class_id

        # Schema = full inherited attribute list
        CLASS_SCHEMAS[name] = full_attrs

        # Class-scoped LOV map (ID-resolved, inherited)
        CLASS_LOV_MAP[name] = full_lov_map

        # Class aliases
        for alias in aliases:
            CLASS_ALIASES[alias.lower()] = name

        # Parent-child relationships
        if children:
            CLASS_TREE_CHILDREN[name] = [c["name"] for c in children]

        # Recurse into children, passing accumulated attrs and LOV map
        if children:
            _flatten_tree(children, full_attrs, attr_name_by_id, full_lov_map, attr_lov_by_id)


# ── Load schema on import ────────────────────────────────────────────────────

def _load_schema() -> None:
    """Load schema from JSON files (Classes.json + Attributes.json), then aliases.json."""
    if _CLASSES_JSON.exists() and _ATTRS_JSON.exists():
        try:
            _load_from_json(_CLASSES_JSON, _ATTRS_JSON)
        except Exception as e:
            warnings.warn(f"Failed to load JSON schema: {e}")
    else:
        warnings.warn(
            "Schema JSON not found. Expected: schema/Classes.json + schema/Attributes.json"
        )
    # Always load aliases.json last — wins on conflict with all other sources
    _load_aliases_json()


def _load_aliases_json() -> None:
    """
    Load schema/aliases.json — only class_aliases section.

    Attribute aliases come exclusively from Attributes.json (name, shortname,
    aliases fields) to avoid LLM-generated aliases overriding correct mappings.

    Class aliases that are themselves KNOWN_CLASS names are rejected to prevent
    catastrophic overwrites (e.g., "Washer" as alias for "Gasket").
    """
    if not _ALIASES_JSON.exists():
        return

    try:
        with open(_ALIASES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        warnings.warn(f"Failed to load aliases.json ({e}), skipping")
        return

    # Build set of known class names (lowercase) to reject as aliases
    known_lower = {c.lower() for c in KNOWN_CLASSES}
    skipped = 0

    # class_aliases: canonical → [aliases]  (used by class_extractor for scoring)
    for canonical, alias_list in data.get("class_aliases", {}).items():
        CLASS_ALIASES[canonical.lower()] = canonical
        for alias in alias_list:
            alias_lower = alias.strip().lower()
            if alias_lower in known_lower:
                # SKIP: a real class name cannot be an alias for another class
                skipped += 1
                continue
            CLASS_ALIASES[alias_lower] = canonical

    print(f"[schema] aliases.json loaded: "
          f"{len(data.get('class_aliases', {}))} class aliases"
          f"{f' ({skipped} conflicting aliases skipped)' if skipped else ''}")


_load_schema()


# ── LOV normalization helper ─────────────────────────────────────────────────

def _normalize_key(s: str) -> str:
    """Lowercase, strip spaces, hyphens, underscores for fuzzy matching.

    Critical: strips underscores so Teamcenter LOVs like "AC_POWER" match
    web-extracted values like "AC Power" and "ac-power".
    """
    return re.sub(r"[\s\-_]", "", s.lower())


def _normalize_to_lov(value: str, lov_values: list[str]) -> str:
    """Match a raw value to a LOV entry using fuzzy comparison.

    "Stainless Steel" -> "StainlessSteel"
    "zinc plated" -> "ZincPlated"
    "AC Power" -> "AC_POWER"
    Returns the original value if no match found.
    """
    matched, _ = _fuzzy_match_lov(value, lov_values)
    return matched if matched is not None else value


def _fuzzy_match_lov(value: str, lov_values: list[str]) -> tuple[str | None, bool]:
    """Try to match `value` to a LOV entry using cascading fuzzy strategies.

    Single-pass over lov_values: each LOV entry is tested against all 3
    strategies in priority order. Exact matches return immediately; substring
    and word-overlap matches are kept as fallbacks.

    Returns:
        (matched_lov_entry, True)  if a match was found
        (None, False)              if no LOV entry matched

    Strategies (in order of strictness):
        1. Exact normalized equality (strips spaces/hyphens/underscores)
        2. Substring containment ("303 stainless steel" -> "stainlesssteel")
        3. Word-overlap (all LOV words appear in value)
    """
    if not value or not lov_values:
        return (None, False)

    norm_val = _normalize_key(value)
    if not norm_val:
        return (None, False)

    val_words = set(re.findall(r"[a-z0-9]+", value.lower()))
    substring_match: str | None = None
    word_overlap_match: str | None = None
    word_overlap_score: int = 0

    for lov_entry in lov_values:
        norm_lov = _normalize_key(lov_entry)
        if not norm_lov:
            continue

        # Strategy 1: exact normalized equality (return immediately)
        if norm_lov == norm_val:
            return (lov_entry, True)

        # Strategy 2: substring containment
        if substring_match is None and (norm_lov in norm_val or norm_val in norm_lov):
            substring_match = lov_entry

        # Strategy 3: word-overlap (split CamelCase + delimiters)
        if val_words:
            lov_words = [w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+", lov_entry) if len(w) >= 2]
            if lov_words:
                overlap = sum(1 for w in lov_words if w in val_words)
                if overlap == len(lov_words) and overlap > word_overlap_score:
                    word_overlap_score = overlap
                    word_overlap_match = lov_entry

    # Strategy 2 wins over Strategy 3 (more specific)
    if substring_match is not None:
        return (substring_match, True)
    if word_overlap_match is not None:
        return (word_overlap_match, True)
    return (None, False)


# ── Public API ───────────────────────────────────────────────────────────────

def get_schema(part_class: str) -> list[str]:
    """Return canonical attribute list for the given class."""
    if part_class in CLASS_SCHEMAS:
        return CLASS_SCHEMAS[part_class]
    # Fuzzy match
    lower = part_class.lower()
    for key, schema in CLASS_SCHEMAS.items():
        if key.lower() in lower or lower in key.lower():
            return schema
    return _DEFAULT_SCHEMA


def get_tc_class_id(part_class: str) -> str:
    """Return Teamcenter class ID for the given class, or empty string."""
    if part_class in TC_CLASS_IDS:
        return TC_CLASS_IDS[part_class]
    lower = part_class.lower()
    for key, tc_id in TC_CLASS_IDS.items():
        if key.lower() == lower:
            return tc_id
    return ""


def _normalize_class_name(name: str) -> str:
    """Normalize a class name for fuzzy matching: lowercase, strip plural suffix."""
    n = name.lower().strip()
    # Strip common plural suffixes
    if n.endswith("ies"):
        n = n[:-3] + "y"
    elif n.endswith("es") and not n.endswith("ses"):
        n = n[:-2]
    elif n.endswith("s") and not n.endswith("ss"):
        n = n[:-1]
    return n


def map_to_json_class(detected_class: str) -> tuple[str, bool]:
    """Map a detected class name to the nearest Classes.json class.

    Returns (mapped_class, found_in_json).
    Matching is case-insensitive and grammar-insensitive (singular/plural).

    Example: "Flat Washer" not in JSON, but "WASHERS" is → returns ("WASHERS", True)
    """
    if not detected_class or detected_class in ("Unclassified", "Unknown", "Error"):
        return detected_class, False

    # Build normalized lookup from JSON classes
    json_classes = list(CLASS_SCHEMAS.keys())
    norm_map = {}  # normalized_name → original JSON class name
    for jc in json_classes:
        norm_map[_normalize_class_name(jc)] = jc

    # 0. Check CLASS_ALIASES — LLM may output an alias name
    alias_lower = detected_class.strip().lower()
    if alias_lower in CLASS_ALIASES:
        resolved = CLASS_ALIASES[alias_lower]
        resolved_norm = _normalize_class_name(resolved)
        if resolved_norm in norm_map:
            return norm_map[resolved_norm], True

    # 1. Exact match (case-insensitive + plural-insensitive)
    detected_norm = _normalize_class_name(detected_class)
    if detected_norm in norm_map:
        return norm_map[detected_norm], True

    # 2. Check if any word in detected class matches a JSON class
    # e.g., "Flat Washer" → check "flat", "washer" against JSON classes
    detected_words = detected_class.lower().split()
    for word in detected_words:
        word_norm = _normalize_class_name(word)
        if word_norm in norm_map:
            return norm_map[word_norm], True

    # 3. Check if detected class is a substring of any JSON class or vice versa
    for jc_norm, jc_original in norm_map.items():
        if detected_norm in jc_norm or jc_norm in detected_norm:
            return jc_original, True

    # 4. Walk parent hierarchy — check if any parent class exists in JSON
    # (uses _PARENT_CHILDREN from class_extractor if available)
    try:
        from src.class_extractor import _CHILD_PARENTS
        current = detected_class
        visited = set()
        while current and current not in visited:
            visited.add(current)
            parents = _CHILD_PARENTS.get(current, set())
            for parent in parents:
                parent_norm = _normalize_class_name(parent)
                if parent_norm in norm_map:
                    return norm_map[parent_norm], True
            # Try next level up
            current = next(iter(parents), None) if parents else None
    except ImportError:
        pass

    # 5. No match — return as-is, not in JSON
    return detected_class, False


def schema_source() -> str:
    """Return 'json' or 'none' indicating where schema was loaded from."""
    return _SCHEMA_SOURCE


def normalize_attrs_with_lov_status(
    raw: dict, part_class: str
) -> tuple[dict[str, str], dict[str, str]]:
    """
    1. Map raw LLM keys to TC attribute names via exact alias lookup.
    2. LOV-normalize values where applicable (with improved fuzzy matching).
    3. Range-average numeric attributes (if datatype is float/double/int).
    4. Track LOV mismatches: values for LOV-governed attrs that didn't match any entry.
    5. Order: TC schema attrs first, then unmatched LLM keys at the end.

    Returns:
        (ordered_attrs, lov_mismatches, range_originals)
        ordered_attrs: dict[canonical_name, value] - the normalized attributes
        lov_mismatches: dict[canonical_name, original_value] - LOV-governed attrs
                        whose value did NOT match any LOV entry
        range_originals: dict[canonical_name, original_range] - TC schema attrs
                         whose range value was averaged (original preserved here)
    """
    from src.range_handler import average_range, fraction_to_decimal, strip_unit_suffix

    schema = get_schema(part_class)
    schema_set = set(schema)

    # Resolve class-scoped LOV map using same fuzzy logic as get_schema
    class_lov = CLASS_LOV_MAP.get(part_class, {})
    if not class_lov:
        # Fuzzy fallback: try case-insensitive then substring match
        lower = part_class.lower()
        for cls_key, lov_map in CLASS_LOV_MAP.items():
            if cls_key.lower() == lower:
                class_lov = lov_map
                break
        if not class_lov:
            for cls_key, lov_map in CLASS_LOV_MAP.items():
                if cls_key.lower() in lower or lower in cls_key.lower():
                    class_lov = lov_map
                    break

    normalized: dict[str, str] = {}
    lov_mismatches: dict[str, str] = {}
    range_originals: dict[str, str] = {}
    fraction_originals: dict[str, str] = {}

    for k, v in raw.items():
        k_lower = k.strip().lower()
        # Exact alias lookup (from Attributes.json name/shortname/aliases) or keep original
        canonical = ALIASES.get(k_lower) or k.strip()
        # Match to schema casing
        for schema_key in schema:
            if schema_key.lower() == canonical.lower():
                canonical = schema_key
                break

        str_val = str(v).strip()
        if not str_val:
            continue

        # LOV normalization: class-scoped only (ID-resolved per class)
        lov_values = class_lov.get(canonical)
        if lov_values:
            matched, ok = _fuzzy_match_lov(str_val, lov_values)
            if ok:
                str_val = matched
            else:
                # Record mismatch (keep original value in normalized too — per user request)
                lov_mismatches[canonical] = str_val

        # Fraction → decimal conversion (preserve original if changed for TC attrs)
        original_before_frac = str_val
        str_val = fraction_to_decimal(str_val)
        if str_val != original_before_frac and canonical in schema_set:
            fraction_originals[canonical] = original_before_frac

        # Range averaging (for numeric attributes) — preserve original if changed
        original_before_avg = str_val
        str_val = average_range(str_val, ATTR_DATATYPES.get(canonical))
        if str_val != original_before_avg and canonical in schema_set:
            range_originals[canonical] = original_before_avg

        # Strip trailing UOM suffix — UOM lives in its own input column
        str_val = strip_unit_suffix(str_val, ATTR_DATATYPES.get(canonical))

        normalized[canonical] = str_val

    # Order: TC schema attrs first, then LLM extras
    ordered: dict[str, str] = {}
    for key in schema:
        if key in normalized:
            ordered[key] = normalized[key]
    for key, val in normalized.items():
        if key not in ordered:
            ordered[key] = val

    return ordered, lov_mismatches, range_originals, fraction_originals


def normalize_attrs(raw: dict, part_class: str) -> dict[str, str]:
    """Backwards-compatible wrapper around normalize_attrs_with_lov_status.

    Returns only the normalized dict (without LOV mismatch tracking).
    """
    ordered, _, _, _ = normalize_attrs_with_lov_status(raw, part_class)
    return ordered
