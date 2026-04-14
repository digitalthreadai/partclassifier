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
- CLASS_ATTR_META: dict[str, dict[str, dict]]   — class name -> {canonical_attr_name -> {type, unit, length, precision, case, sign}}
                                       ID-resolved per class; only populated for attrs that have these fields in Attributes.json
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
CLASS_ATTR_META: dict[str, dict[str, dict]] = {}     # class_name -> {canonical_attr_name -> {type,unit,length,precision,case,sign}}
CLASS_ATTR_IDS: dict[str, dict[str, str]] = {}       # class_name -> {canonical_attr_name -> attr_id_string}
                                                     # child-wins: each class records the ID it actually uses per attr
CLASS_DIRECT_ATTRS: dict[str, set[str]] = {}         # class_name -> set of attr names in THIS class's own attributeslist
                                                     # (excludes inherited attrs from parents)
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
    global KNOWN_CLASSES, TC_CLASS_IDS, CLASS_SCHEMAS, CLASS_LOV_MAP, CLASS_ATTR_META
    global CLASS_ATTR_IDS, CLASS_DIRECT_ATTRS
    global ALIASES, CLASS_ALIASES, CLASS_TREE_CHILDREN, ATTR_DICT, _DEFAULT_SCHEMA, _SCHEMA_SOURCE

    # --- Load attributes ---
    with open(attrs_path, "r", encoding="utf-8") as f:
        attrs_data = json.load(f)

    attr_by_id: dict[str, dict] = {}
    attr_name_by_id: dict[str, str] = {}
    attr_lov_by_id: dict[str, list[str]] = {}    # id -> lov_values (for class-scoped lookup)
    attr_meta_by_id: dict[str, dict] = {}        # id -> {type, unit, length, precision, case, sign}

    _META_FIELDS = ("type", "unit", "length", "precision", "case", "sign")

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

        # Populate attr_meta_by_id with new type metadata fields (if present)
        meta = {f: attr[f] for f in _META_FIELDS if attr.get(f) is not None}
        # Cast integer fields to int — Attributes.json may store them as quoted strings
        for _int_field in ("length", "precision", "case", "sign"):
            if _int_field in meta:
                try:
                    meta[_int_field] = int(meta[_int_field])
                except (ValueError, TypeError):
                    pass
        if meta:
            attr_meta_by_id[aid] = meta

    # --- Load classes ---
    with open(classes_path, "r", encoding="utf-8") as f:
        classes_data = json.load(f)

    # Flatten the class tree, computing inherited attributes, LOV maps, and type metadata
    _flatten_tree(
        classes_data.get("tree", classes_data.get("classes", [])),
        inherited_attrs=[],
        attr_name_by_id=attr_name_by_id,
        inherited_lov_map={},
        attr_lov_by_id=attr_lov_by_id,
        inherited_meta_map={},
        attr_meta_by_id=attr_meta_by_id,
        inherited_id_map={},
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
    inherited_meta_map: dict[str, dict],
    attr_meta_by_id: dict[str, dict],
    inherited_id_map: dict[str, str],
) -> None:
    """Recursively walk the class tree, populating module-level data.

    Each node accumulates inherited attributes from ancestors plus its own
    directly-assigned attributes. Only leaf and named intermediate classes
    are added to KNOWN_CLASSES.

    Child-wins rule: when a class re-declares an attribute that exists in a parent
    (same name, different attr ID), the child's ID takes precedence for LOV, type
    metadata, and the per-class ID map (CLASS_ATTR_IDS). The child class's own
    attributeslist definition is always authoritative for that class's context.

    Attribute ordering in CLASS_SCHEMAS still uses first-wins (inherited attrs come
    first in parent order, child's NEW attrs appended) — no duplicates by name.
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

        # Full attribute list = inherited + direct (no duplicates by name, order preserved)
        # Ordering uses first-wins: inherited attrs keep parent position; only truly NEW
        # attr names (not already inherited) are appended from the direct list.
        full_attrs = list(inherited_attrs)
        for a in direct_attr_names:
            if a not in full_attrs:
                full_attrs.append(a)

        # Build per-class attr-name → attr-id map.
        # CHILD-WINS: this class's own attributeslist IDs overwrite any inherited ID
        # for the same attr name. Ensures correct ID is used per class context.
        full_id_map: dict[str, str] = dict(inherited_id_map)
        for aid in node.get("attributeslist", []):
            aname = attr_name_by_id.get(str(aid))
            if aname:
                full_id_map[aname] = str(aid)  # always overwrite — child wins

        # Build class-scoped LOV map.
        # CHILD-WINS: this class's own attributeslist IDs overwrite any inherited LOV.
        full_lov_map: dict[str, list[str]] = dict(inherited_lov_map)
        for aid in node.get("attributeslist", []):
            aname = attr_name_by_id.get(str(aid))
            if aname:
                lov = attr_lov_by_id.get(str(aid))
                if lov:
                    full_lov_map[aname] = lov  # always overwrite — child wins

        # Build class-scoped type metadata map.
        # CHILD-WINS: this class's own attributeslist IDs overwrite any inherited meta.
        full_meta_map: dict[str, dict] = dict(inherited_meta_map)
        for aid in node.get("attributeslist", []):
            aname = attr_name_by_id.get(str(aid))
            if aname:
                meta = attr_meta_by_id.get(str(aid))
                if meta:
                    full_meta_map[aname] = meta  # always overwrite — child wins

        # Register this class
        KNOWN_CLASSES.append(name)
        TC_CLASS_IDS[name] = class_id
        CLASS_SCHEMAS[name] = full_attrs
        CLASS_LOV_MAP[name] = full_lov_map
        CLASS_ATTR_META[name] = full_meta_map
        CLASS_ATTR_IDS[name] = full_id_map
        CLASS_DIRECT_ATTRS[name] = set(direct_attr_names)

        # Class aliases
        for alias in aliases:
            CLASS_ALIASES[alias.lower()] = name

        # Parent-child relationships
        if children:
            CLASS_TREE_CHILDREN[name] = [c["name"] for c in children]

        # Recurse into children, passing accumulated attrs, LOV map, meta map, and ID map
        if children:
            _flatten_tree(
                children, full_attrs, attr_name_by_id,
                full_lov_map, attr_lov_by_id,
                full_meta_map, attr_meta_by_id,
                full_id_map,
            )


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


# ── Class schema detail (for debug logging) ──────────────────────────────────

def get_class_schema_detail(part_class: str) -> str:
    """Return a multi-line string describing the schema for a part class.

    Shows TC class ID, then one line per attribute with its JSON id and metadata.
    Each attr's ID comes from CLASS_ATTR_IDS — the per-class, child-wins map that
    records exactly which attr ID this class is using for each attr name.
    Used for DEBUG_MODE console/log output to validate schema loading.
    """
    schema_attrs = CLASS_SCHEMAS.get(part_class, [])
    tc_id = TC_CLASS_IDS.get(part_class, "?")
    meta_map = CLASS_ATTR_META.get(part_class, {})
    lov_map = CLASS_LOV_MAP.get(part_class, {})
    id_map = CLASS_ATTR_IDS.get(part_class, {})   # per-class correct IDs

    lines = [
        f"  Schema  : {part_class}  (TC class ID: {tc_id})  [{len(schema_attrs)} attrs]",
    ]
    direct_set = CLASS_DIRECT_ATTRS.get(part_class, set())
    for attr in schema_attrs:
        attr_id = id_map.get(attr, "?")            # correct ID for THIS class
        inherited_marker = "" if attr in direct_set else " (inherited)"
        meta = meta_map.get(attr, {})
        lov = lov_map.get(attr)

        # Build compact tag string: type | unit | len=N | prec=N | LOV(N)
        tags: list[str] = []
        if meta.get("type"):
            tags.append(meta["type"])
        if meta.get("unit"):
            tags.append(f"unit={meta['unit']}")
        if meta.get("length") is not None:
            tags.append(f"len={meta['length']}")
        if meta.get("precision") is not None:
            tags.append(f"prec={meta['precision']}")
        if meta.get("case") is not None:
            tags.append(f"case={meta['case']}")
        if meta.get("sign") is not None:
            tags.append(f"sign={meta['sign']}")
        if lov:
            tags.append(f"LOV({len(lov)})")

        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        lines.append(f"    id={attr_id:<8} {attr}{tag_str}{inherited_marker}")

    return "\n".join(lines)


# ── Class-map lookup helper ──────────────────────────────────────────────────

def _resolve_class_map(d: dict, part_class: str) -> dict:
    """Fuzzy class key lookup: exact → case-insensitive → substring.

    Used for CLASS_LOV_MAP, CLASS_ATTR_META, and any other class-keyed dict.
    Returns empty dict when no match found.
    """
    if not part_class:
        return {}
    if part_class in d:
        return d[part_class]
    lower = part_class.lower()
    for k, v in d.items():
        if k.lower() == lower:
            return v
    for k, v in d.items():
        if k.lower() in lower or lower in k.lower():
            return v
    return {}


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


def _fuzzy_match_lov(value: str, lov_values: list[str], case_sensitive: bool = False) -> tuple[str | None, bool]:
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

    # case_sensitive=True: exact string match only, no normalization
    if case_sensitive:
        return (value, True) if value in lov_values else (None, False)

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
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Normalize raw LLM-extracted attributes for the given part class.

    Operation order per attribute:
      1. Fraction → decimal conversion
      2. Range averaging          (class-scoped type from CLASS_ATTR_META)
      3. Strip unit suffix        (class-scoped type from CLASS_ATTR_META)
      4. apply_precision          (float/double only; before LOV so LOV sees final value)
      5. LOV normalization        (class-scoped; case_sensitive when attr.case == 1)
      6. apply_length             (string: truncate + record original; numeric: log only)
      7. apply_sign               (integer only; violated values are DROPPED with warning)

    Returns:
        (ordered_attrs, lov_mismatches, pre_conversion_originals)

        pre_conversion_originals holds the earliest pre-conversion value for each attr
        that was changed by any of: fraction→decimal, range averaging, precision rounding,
        or string length truncation. Only the first change per attr is recorded.
    """
    from src.range_handler import (
        average_range, fraction_to_decimal, strip_unit_suffix, strip_tolerance,
        apply_precision, apply_length, apply_sign, get_type_behavior,
    )

    schema = get_schema(part_class)
    schema_set = set(schema)

    # Resolve class-scoped maps using shared fuzzy helper
    class_lov = _resolve_class_map(CLASS_LOV_MAP, part_class)
    class_attr_meta = _resolve_class_map(CLASS_ATTR_META, part_class)

    normalized: dict[str, str] = {}
    lov_mismatches: dict[str, str] = {}
    pre_conversion_originals: dict[str, str] = {}

    def _record_original(attr: str, original: str) -> None:
        """Store original value only on the first conversion for this attr."""
        if attr in schema_set and attr not in pre_conversion_originals:
            pre_conversion_originals[attr] = original

    for k, v in raw.items():
        k_lower = k.strip().lower()
        canonical = ALIASES.get(k_lower) or k.strip()
        for schema_key in schema:
            if schema_key.lower() == canonical.lower():
                canonical = schema_key
                break

        str_val = str(v).strip()
        if not str_val:
            continue

        # Get class-scoped type metadata for this attribute (ID-resolved, no global fallback)
        attr_meta = class_attr_meta.get(canonical, {})
        attr_type = attr_meta.get("type")
        behavior = get_type_behavior(attr_type) if attr_type else {}

        # Step 0: Strip tolerance notation (applies universally — "+/-"/± pattern is specific enough)
        # Runs regardless of type so attrs without a defined type are also cleaned.
        original_before_tol = str_val
        str_val = strip_tolerance(str_val)
        if str_val != original_before_tol:
            _record_original(canonical, original_before_tol)

        # Step 1: Fraction → decimal (only for types that support it)
        if not attr_type or behavior.get("fraction_to_decimal", True):
            original_before_frac = str_val
            str_val = fraction_to_decimal(str_val)
            if str_val != original_before_frac:
                _record_original(canonical, original_before_frac)

        # Step 2: Range averaging (use class-scoped type, no global fallback)
        original_before_avg = str_val
        str_val = average_range(str_val, attr_type)
        if str_val != original_before_avg:
            _record_original(canonical, original_before_avg)

        # Step 3: Strip unit suffix (use class-scoped type)
        str_val = strip_unit_suffix(str_val, attr_type)

        # Step 4: Apply precision (float/double only; before LOV so LOV sees rounded value)
        if behavior.get("apply_precision") and attr_meta.get("precision") is not None:
            original_before_precision = str_val
            str_val = apply_precision(str_val, attr_meta["precision"])
            if str_val != original_before_precision:
                _record_original(canonical, original_before_precision)

        # Step 5: LOV normalization (class-scoped; respects case field)
        lov_values = class_lov.get(canonical)
        if lov_values:
            case_sensitive = attr_meta.get("case", 0) == 1
            matched, ok = _fuzzy_match_lov(str_val, lov_values, case_sensitive=case_sensitive)
            if ok:
                str_val = matched
            else:
                lov_mismatches[canonical] = str_val

        # Step 6: Apply length (string: truncate + record original; numeric: log only)
        if attr_meta.get("length") is not None:
            str_val, length_original = apply_length(str_val, attr_meta["length"], attr_type or "")
            if length_original is not None:
                _record_original(canonical, length_original)

        # Step 7: Apply sign (integer only; drop value if violated)
        if behavior.get("apply_sign") and attr_meta.get("sign") is not None:
            if not apply_sign(str_val, attr_meta["sign"]):
                print(f"  [AttrType] Sign violation: '{canonical}' = '{str_val}' "
                      f"(sign={attr_meta['sign']} requires {'non-negative' if attr_meta['sign'] == 0 else 'non-positive'}) — value dropped")
                continue  # skip normalized[canonical] = str_val for this attr

        normalized[canonical] = str_val

    # Order: TC schema attrs first, then LLM extras
    ordered: dict[str, str] = {}
    for key in schema:
        if key in normalized:
            ordered[key] = normalized[key]
    for key, val in normalized.items():
        if key not in ordered:
            ordered[key] = val

    return ordered, lov_mismatches, pre_conversion_originals


def normalize_attrs(raw: dict, part_class: str) -> dict[str, str]:
    """Backwards-compatible wrapper around normalize_attrs_with_lov_status.

    Returns only the normalized dict (without LOV mismatch tracking).
    """
    ordered, _, _ = normalize_attrs_with_lov_status(raw, part_class)
    return ordered
