"""
Canonical attribute names and normalization for each part class.

PURPOSE
-------
Different web sources (distributors, catalog sites) use different names for
the same attribute: "Screw Size", "Thread Size", "For Screw Size" all mean
the same thing. This module maps every known alias to a single canonical key
so that all parts of the same class produce identical Excel columns.

HOW IT WORKS
------------
1. CLASS_SCHEMAS: defines the ordered list of canonical attribute names for
   each class. The LLM extraction prompt is given these names so it targets
   them directly (primary normalization).
2. ALIASES: a global alias → canonical mapping applied as a post-processing
   pass in case the LLM still produces a variant name (secondary normalization).
3. normalize_attrs(): applies both passes and returns a clean ordered dict.
"""

from typing import OrderedDict


# ── Canonical attribute lists per class ───────────────────────────────────────
# These are the exact column names that will appear in the output Excel.
# Order here = column order in the output file.

CLASS_SCHEMAS: dict[str, list[str]] = {
    # ── Washers ───────────────────────────────────────────────────────────────
    "Flat Washer": [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Washer Type", "Performance",
    ],
    "Fender Washer": [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Washer Type",
    ],
    "Split Lock Washer": [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Washer Type", "Performance",
        "RoHS", "REACH",
    ],
    "Lock Washer": [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Washer Type", "Performance",
    ],
    "Internal Tooth Lock Washer": [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Washer Type",
    ],
    "External Tooth Lock Washer": [
        "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Washer Type",
    ],
    # ── Nuts ─────────────────────────────────────────────────────────────────
    "Hex Nut": [
        "Thread Size", "Thread Pitch", "Width Across Flats", "Height",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Nut Type",
    ],
    "Lock Nut": [
        "Thread Size", "Thread Pitch", "Width Across Flats", "Height",
        "Material", "Finish", "Hardness", "Standard",
        "System of Measurement", "Nut Type",
    ],
    # ── Bolts / Screws ────────────────────────────────────────────────────────
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
    "Set Screw": [
        "Thread Size", "Thread Pitch", "Length", "Drive Type",
        "Point Type", "Material", "Finish", "Hardness", "Standard",
        "System of Measurement",
    ],
    # ── Pins ─────────────────────────────────────────────────────────────────
    "Dowel Pin": [
        "Diameter", "Length", "Tolerance", "Material", "Finish",
        "Hardness", "Standard", "System of Measurement",
    ],
    "Cotter Pin": [
        "Diameter", "Length", "Material", "Finish",
        "Standard", "System of Measurement",
    ],
}

# Default schema for classes not listed above
_DEFAULT_SCHEMA: list[str] = [
    "Screw Size", "Inner Diameter", "Outer Diameter", "Thickness", "Length",
    "Material", "Finish", "Hardness", "Standard",
    "System of Measurement", "Performance",
]


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


# ── Global alias → canonical mapping ──────────────────────────────────────────
# Key: lowercased alias  |  Value: canonical display name

ALIASES: dict[str, str] = {
    # Screw / thread size
    "screw size":            "Screw Size",
    "for screw size":        "Screw Size",
    "thread size":           "Screw Size",
    "thread":                "Screw Size",
    "nominal thread size":   "Screw Size",
    "bolt size":             "Screw Size",
    "fastener size":         "Screw Size",
    # Inner diameter
    "id":                    "Inner Diameter",
    "inner diameter":        "Inner Diameter",
    "inner dia":             "Inner Diameter",
    "bore diameter":         "Inner Diameter",
    "bore":                  "Inner Diameter",
    "hole diameter":         "Inner Diameter",
    "hole size":             "Inner Diameter",
    # Outer diameter
    "od":                    "Outer Diameter",
    "outer diameter":        "Outer Diameter",
    "outer dia":             "Outer Diameter",
    "outside diameter":      "Outer Diameter",
    # Thickness
    "thk":                   "Thickness",
    "thickness":             "Thickness",
    "height":                "Thickness",
    "thickness range":       "Thickness",
    # Material
    "material":              "Material",
    "material type":         "Material",
    # Finish / coating
    "finish":                "Finish",
    "coating":               "Finish",
    "surface finish":        "Finish",
    "plating":               "Finish",
    # Standard / specification
    "standard":              "Standard",
    "specifications met":    "Standard",
    "specs met":             "Standard",
    "specification":         "Standard",
    "spec":                  "Standard",
    "norm":                  "Standard",
    # System of measurement
    "system of measurement": "System of Measurement",
    "measurement system":    "System of Measurement",
    "unit system":           "System of Measurement",
    # Hardness
    "hardness":              "Hardness",
    "hardness rating":       "Hardness",
    # Performance / use
    "performance":           "Performance",
    "corrosion resistance":  "Performance",
    # Washer type
    "washer type":           "Washer Type",
    "type":                  "Washer Type",
    # Compliance
    "rohs":                  "RoHS",
    "reach":                 "REACH",
    # ── DigiKey / Mouser API parameter names ──
    "screw/bolt size":       "Screw Size",
    "inside diameter":       "Inner Diameter",
    "outside diameter":      "Outer Diameter",
    "overall thickness":     "Thickness",
    "material - body":       "Material",
    "body material":         "Material",
    "surface treatment":     "Finish",
    "surface finish":        "Finish",
    "drive style":           "Drive Type",
    "drive type":            "Drive Type",
    "head type":             "Washer Type",
    "overall length":        "Length",
    "head style":            "Washer Type",
    "thread pitch - metric": "Thread Pitch",
    "threads per inch":      "Thread Pitch",
}


# ── Public API ─────────────────────────────────────────────────────────────────

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
