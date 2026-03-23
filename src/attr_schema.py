"""
Canonical attribute names and normalization for each part class.

SCHEMA SOURCE
-------------
Reads from `input/ClassificationSchema.xlsx` (two sheets: Classes, Attributes).
Falls back to hardcoded defaults if the Excel file is missing or unreadable.

HOW IT WORKS
------------
1. KNOWN_CLASSES: list of all valid part class names (from Classes sheet).
2. TC_CLASS_IDS: maps class name -> Teamcenter class ID (from Classes sheet).
3. CLASS_SCHEMAS: maps class -> ordered list of canonical attribute names
   (built from Attributes sheet; `*` means all classes).
4. ALIASES: global alias -> canonical mapping (from Attributes sheet aliases column).
5. normalize_attrs(): applies alias normalization + schema ordering.
"""

import warnings
from pathlib import Path
from typing import OrderedDict

import openpyxl


# ── Schema file location ─────────────────────────────────────────────────────

_SCHEMA_PATH = Path(__file__).parent.parent / "input" / "ClassificationSchema.xlsx"


# ── Module-level data (populated by _load_schema at import time) ──────────────

KNOWN_CLASSES: list[str] = []
TC_CLASS_IDS: dict[str, str] = {}       # class_name -> Teamcenter class ID
CLASS_SCHEMAS: dict[str, list[str]] = {}
ALIASES: dict[str, str] = {}
_DEFAULT_SCHEMA: list[str] = []
_SCHEMA_SOURCE: str = "none"            # "excel" or "hardcoded"


# ── Excel loader ──────────────────────────────────────────────────────────────

def _load_from_excel(path: Path) -> None:
    """Load schema from ClassificationSchema.xlsx."""
    global KNOWN_CLASSES, TC_CLASS_IDS, CLASS_SCHEMAS, ALIASES, _DEFAULT_SCHEMA, _SCHEMA_SOURCE

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    # --- Sheet 1: Classes ---
    if "Classes" not in wb.sheetnames:
        raise ValueError("Sheet 'Classes' not found in ClassificationSchema.xlsx")

    ws_classes = wb["Classes"]
    for row in ws_classes.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        name = str(row[0]).strip()
        tc_id = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        if name:
            KNOWN_CLASSES.append(name)
            if tc_id:
                TC_CLASS_IDS[name] = tc_id

    # --- Sheet 2: Attributes ---
    if "Attributes" not in wb.sheetnames:
        raise ValueError("Sheet 'Attributes' not found in ClassificationSchema.xlsx")

    ws_attrs = wb["Attributes"]
    for row in ws_attrs.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        attr_name = str(row[0]).strip()
        classes_str = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        aliases_str = str(row[2]).strip() if len(row) > 2 and row[2] else ""

        if not attr_name:
            continue

        # Parse applicable classes
        if classes_str == "*":
            applicable = set(KNOWN_CLASSES)
        else:
            applicable = {c.strip() for c in classes_str.split(";") if c.strip()}
            # Warn about unknown class references
            for cls in applicable:
                if cls not in KNOWN_CLASSES:
                    warnings.warn(
                        f"ClassificationSchema.xlsx: Attribute '{attr_name}' references "
                        f"unknown class '{cls}' (not in Classes sheet)"
                    )

        # Add to CLASS_SCHEMAS for each applicable class
        for cls in applicable:
            if cls in KNOWN_CLASSES:  # Only add for known classes
                CLASS_SCHEMAS.setdefault(cls, []).append(attr_name)

        # Parse aliases
        # Always add the canonical name itself (lowercased)
        ALIASES[attr_name.lower()] = attr_name
        if aliases_str:
            for alias in aliases_str.split(";"):
                alias = alias.strip().lower()
                if alias:
                    ALIASES[alias] = attr_name

    wb.close()

    # Build default schema from universal (*) attributes
    _DEFAULT_SCHEMA = [
        a for a in ALIASES.values()
        if a in {attr_name for attr_name in dict.fromkeys(
            ALIASES.values()  # unique canonical names
        )}
    ]
    # Simpler: just use a reasonable default
    _DEFAULT_SCHEMA = [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness", "Length",
        "Width", "Height", "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Performance", "RoHS", "REACH",
    ]

    _SCHEMA_SOURCE = "excel"

    # Validate aliases are all strings
    assert all(isinstance(v, str) for v in ALIASES.values()), \
        "All ALIASES values must be strings"


# ── Hardcoded fallback (backward compatibility) ───────────────────────────────

def _load_hardcoded_defaults() -> None:
    """Fallback: populate from hardcoded data when Excel is missing."""
    global KNOWN_CLASSES, TC_CLASS_IDS, CLASS_SCHEMAS, ALIASES, _DEFAULT_SCHEMA, _SCHEMA_SOURCE

    KNOWN_CLASSES.extend([
        # Fasteners
        "Washer", "Lock Washer", "Split Lock Washer", "Flat Washer",
        "Fender Washer", "Internal Tooth Lock Washer", "External Tooth Lock Washer",
        "Nut", "Lock Nut", "Hex Nut", "Wing Nut",
        "Bolt", "Hex Bolt", "Carriage Bolt",
        "Screw", "Cap Screw", "Set Screw", "Machine Screw", "Socket Head Cap Screw",
        "Hook", "Eye Bolt", "Eye Hook",
        "Pin", "Cotter Pin", "Dowel Pin", "Roll Pin",
        "Rivet", "Blind Rivet",
        "Clip", "E-Clip", "C-Clip",
        "Ring", "Retaining Ring",
        "Bushing", "Spacer", "Standoff",
        "Stud", "Insert", "Anchor",
        "Spring", "Compression Spring", "Bracket",
        # Seals & Fittings
        "O-Ring", "Seal", "Gasket",
        "Tube Fitting", "VCR Fitting", "Pipe Fitting",
        # Pneumatics & Hydraulics
        "Solenoid Valve", "Pneumatic Valve", "Pneumatic Cylinder",
        "Flow Controller", "Pressure Regulator",
        # Bearings & Linear Motion
        "Ball Bearing", "Deep Groove Ball Bearing", "Angular Contact Bearing",
        "Needle Bearing", "Crossed Roller Bearing",
        "Linear Guide", "Linear Block", "Ball Screw",
        # Sensors & Electrical
        "Proximity Sensor", "Photoelectric Sensor", "Fiber Optic Sensor",
        "Laser Sensor", "Pressure Sensor",
        "Connector", "Terminal", "Relay", "Timer",
        # Vacuum & Semiconductor
        "Vacuum Valve", "Gate Valve", "Vacuum Pump Accessory",
        "Wafer Shipper", "Wafer Carrier",
        "Filter", "Gas Filter", "Liquid Filter",
        "Mass Flow Controller", "Pressure Gauge", "Vacuum Gauge",
    ])

    CLASS_SCHEMAS.update({
        "Flat Washer": [
            "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
            "Material", "Finish", "Hardness", "Standard",
            "System of Measurement", "Washer Type", "Performance",
        ],
        "Split Lock Washer": [
            "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
            "Material", "Finish", "Hardness", "Standard",
            "System of Measurement", "Washer Type", "Performance",
            "RoHS", "REACH",
        ],
        "Hex Nut": [
            "Thread Size", "Thread Pitch", "Width Across Flats", "Height",
            "Material", "Finish", "Hardness", "Standard",
            "System of Measurement", "Nut Type",
        ],
        "Hex Bolt": [
            "Thread Size", "Thread Pitch", "Length", "Width Across Flats",
            "Head Height", "Material", "Finish", "Hardness", "Grade", "Standard",
            "System of Measurement",
        ],
        "Cap Screw": [
            "Thread Size", "Thread Pitch", "Length", "Head Diameter",
            "Head Height", "Drive Type", "Material", "Finish", "Hardness",
            "Grade", "Standard", "System of Measurement",
        ],
    })

    ALIASES.update({
        "screw size": "Screw Size", "for screw size": "Screw Size",
        "thread size": "Screw Size", "thread": "Screw Size",
        "nominal thread size": "Screw Size", "bolt size": "Screw Size",
        "id": "Inner Diameter", "inner diameter": "Inner Diameter",
        "inner dia": "Inner Diameter", "bore diameter": "Inner Diameter",
        "bore": "Inner Diameter", "hole diameter": "Inner Diameter",
        "od": "Outer Diameter", "outer diameter": "Outer Diameter",
        "outside diameter": "Outer Diameter",
        "thk": "Thickness", "thickness": "Thickness",
        "height": "Height", "thickness range": "Thickness",
        "material": "Material", "material type": "Material",
        "finish": "Finish", "coating": "Finish", "surface finish": "Finish",
        "plating": "Finish", "surface treatment": "Finish",
        "standard": "Standard", "specifications met": "Standard",
        "spec": "Standard", "norm": "Standard",
        "system of measurement": "System of Measurement",
        "hardness": "Hardness", "hardness rating": "Hardness",
        "performance": "Performance",
        "washer type": "Washer Type", "type": "Washer Type",
        "rohs": "RoHS", "reach": "REACH",
        "screw/bolt size": "Screw Size", "inside diameter": "Inner Diameter",
        "overall thickness": "Thickness", "body material": "Material",
        "material - body": "Material", "drive style": "Drive Type",
        "drive type": "Drive Type", "overall length": "Length",
        "thread pitch - metric": "Thread Pitch",
        "threads per inch": "Thread Pitch",
    })

    _DEFAULT_SCHEMA = [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness", "Length",
        "Width", "Height", "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Performance", "RoHS", "REACH",
    ]

    _SCHEMA_SOURCE = "hardcoded"


# ── Load schema on import ─────────────────────────────────────────────────────

def _load_schema() -> None:
    """Load schema from Excel, falling back to hardcoded defaults."""
    if _SCHEMA_PATH.exists():
        try:
            _load_from_excel(_SCHEMA_PATH)
            return
        except Exception as e:
            warnings.warn(
                f"Failed to load ClassificationSchema.xlsx ({e}), using hardcoded defaults"
            )
    else:
        warnings.warn(
            f"ClassificationSchema.xlsx not found at {_SCHEMA_PATH}, using hardcoded defaults"
        )
    _load_hardcoded_defaults()


_load_schema()


# ── Public API ────────────────────────────────────────────────────────────────

def get_schema(part_class: str) -> list[str]:
    """Return canonical attribute list for the given class."""
    # Exact match first
    if part_class in CLASS_SCHEMAS:
        return CLASS_SCHEMAS[part_class]
    # Fuzzy match — find closest key
    lower = part_class.lower()
    for key, schema in CLASS_SCHEMAS.items():
        if key.lower() in lower or lower in key.lower():
            return schema
    return _DEFAULT_SCHEMA


def get_tc_class_id(part_class: str) -> str:
    """Return Teamcenter class ID for the given class, or empty string."""
    if part_class in TC_CLASS_IDS:
        return TC_CLASS_IDS[part_class]
    # Fuzzy match
    lower = part_class.lower()
    for key, tc_id in TC_CLASS_IDS.items():
        if key.lower() == lower:
            return tc_id
    return ""


def schema_source() -> str:
    """Return 'excel' or 'hardcoded' indicating where schema was loaded from."""
    return _SCHEMA_SOURCE


def normalize_attrs(raw: dict, part_class: str) -> dict[str, str]:
    """
    1. Alias-normalize all keys in `raw`.
    2. Order them according to the class schema (unknown keys go at the end).
    Returns a plain dict with consistent, canonical keys.
    """
    schema = get_schema(part_class)

    # Step 1: normalize keys
    normalized: dict[str, str] = {}
    for k, v in raw.items():
        canonical = ALIASES.get(k.strip().lower(), k.strip())
        # Prefer schema-cased version if available
        for schema_key in schema:
            if schema_key.lower() == canonical.lower():
                canonical = schema_key
                break
        normalized[canonical] = str(v).strip()

    # Step 2: order by schema, then append any extras not in schema
    ordered: dict[str, str] = {}
    for key in schema:
        if key in normalized:
            ordered[key] = normalized[key]
    for key, val in normalized.items():
        if key not in ordered:
            ordered[key] = val

    return ordered
