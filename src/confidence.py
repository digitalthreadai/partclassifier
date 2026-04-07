"""
Per-part quality metrics for extraction coverage and classification confidence.

All functions are pure — no side effects, no LLM calls.
Metrics are computed from data already available in the pipeline.
"""

import re
from src.attr_schema import ALIASES, LOV_MAP, get_schema


# ── Column 1: Attributes Extraction Coverage % ──────────────────────────────

def compute_extraction_coverage(attributes: dict, part_class: str) -> float:
    """Percentage of TC schema attributes that were successfully extracted.

    Returns 0-100. Higher = more complete TC attribute coverage.
    """
    schema = get_schema(part_class)
    if not schema:
        return 0.0

    schema_lower = {s.lower() for s in schema}
    # Normalize extracted keys through ALIASES (same as normalize_attrs)
    matched = 0
    for k in attributes:
        k_lower = k.strip().lower()
        canonical = ALIASES.get(k_lower, k.strip()).lower()
        if canonical in schema_lower:
            matched += 1

    return round(matched / len(schema) * 100, 1)


# ── Column 2: Source Reliability % ──────────────────────────────────────────

_SOURCE_SCORES = {
    "spec file": 100,    # Local spec is the most authoritative source
    "api": 100,
    "stealth": 80,
    "web (cached)": 75,
    "web": 60,
    "part name": 20,
    "none": 0,
}


def compute_source_reliability(
    source_name: str,
    mfg_pn_in_content: bool,
    attributes: dict,
    part_class: str,
    regex_agreement: dict | None = None,
) -> float:
    """Weighted reliability score based on data source quality.

    Weights: source type (40%) + MFG PN match (20%) + coverage (20%) + regex agreement (20%).
    Returns 0-100.
    """
    # Source type score (40%)
    src_type = get_source_type(source_name).lower()
    source_score = _SOURCE_SCORES.get(src_type, 50)

    # MFG PN in content (20%)
    pn_score = 100 if mfg_pn_in_content else 0

    # Coverage as a signal (20%)
    coverage = compute_extraction_coverage(attributes, part_class)

    # Regex/LLM agreement (20%)
    if regex_agreement:
        agreed = regex_agreement.get("agreed", 0)
        disagreed = regex_agreement.get("disagreed", 0)
        total = agreed + disagreed
        agreement_score = (agreed / total * 100) if total > 0 else 50
    else:
        agreement_score = 50  # neutral when no regex data

    return round(
        source_score * 0.4
        + pn_score * 0.2
        + coverage * 0.2
        + agreement_score * 0.2,
        1,
    )


# ── Column 3: Classification Confidence % ───────────────────────────────────

_CLASSIFY_SOURCE_SCORES = {
    "web_high": 100,   # web content, high-scoring match (breadcrumb/label)
    "web_low": 80,     # web content, lower-scoring match
    "cache": 75,       # LLM cache hit
    "llm": 60,         # LLM classification
    "fallback": 30,    # part name or mfg info fallback
}

_VALIDATION_SCORES = {
    "confirmed_high": 100,    # confirmed with score >= 3
    "confirmed_low": 70,      # confirmed with low score
    "reclassified_strong": 90,  # reclassified with large margin
    "reclassified_weak": 70,  # reclassified with minimum margin
    "abstained": 50,          # not enough evidence to validate
    "no_validation": 40,      # validation didn't run (no content)
}


def compute_classification_confidence(
    classify_source: str,
    validation_reason: str,
    in_json: bool,
) -> float:
    """Weighted classification confidence score.

    Weights: classify source (40%) + validation result (40%) + in_json (20%).
    Returns 0-100.
    """
    # Source score (40%)
    source_score = _CLASSIFY_SOURCE_SCORES.get(classify_source, 50)

    # Validation score (40%)
    validation_score = _parse_validation_score(validation_reason)

    # In JSON (20%)
    json_score = 100 if in_json else 30

    return round(
        source_score * 0.4
        + validation_score * 0.4
        + json_score * 0.2,
        1,
    )


def _parse_validation_score(reason: str) -> float:
    """Extract confidence level from validation reason string."""
    if not reason:
        return _VALIDATION_SCORES["no_validation"]

    reason_lower = reason.lower()

    if "reclassified" in reason_lower:
        # Extract scores from "reclassified: X=N > Y=M"
        match = re.search(r"=(\d+)\s*>\s*\w.*=(\d+)", reason)
        if match:
            winner = int(match.group(1))
            loser = int(match.group(2))
            margin = winner - loser
            return _VALIDATION_SCORES["reclassified_strong"] if margin >= 3 else _VALIDATION_SCORES["reclassified_weak"]
        return _VALIDATION_SCORES["reclassified_weak"]

    if "confirmed" in reason_lower:
        match = re.search(r"score=(\d+)", reason)
        if match:
            score = int(match.group(1))
            return _VALIDATION_SCORES["confirmed_high"] if score >= 3 else _VALIDATION_SCORES["confirmed_low"]
        return _VALIDATION_SCORES["confirmed_low"]

    if "kept" in reason_lower:
        if "low evidence" in reason_lower or "too few" in reason_lower:
            return _VALIDATION_SCORES["abstained"]
        return _VALIDATION_SCORES["abstained"]

    return _VALIDATION_SCORES["no_validation"]


# ── Column 4: Source Type ───────────────────────────────────────────────────

def get_source_type(source_name: str) -> str:
    """Map source_name to a clean display string."""
    if not source_name:
        return "None"
    s = source_name.lower()
    if s.startswith("file/") or "spec file" in s:
        return "Spec File"
    if "api" in s or "digikey" in s or "mouser" in s or "mcmaster" in s:
        return "API"
    if "stealth" in s:
        return "Stealth"
    if "cached" in s:
        return "Web (cached)"
    if "part name" in s or source_name == "part name" or source_name == "part name (fallback)":
        return "Part Name"
    if s in ("web", "none", ""):
        return "Web" if s == "web" else "None"
    return "Web"


# ── Column 5: LOV Compliance % ─────────────────────────────────────────────

def compute_lov_compliance(attributes: dict, part_class: str, lov_mismatches: dict | None = None) -> float:
    """Percentage of LOV-governed TC attributes whose values match a valid LOV entry.

    Uses lov_mismatches (from normalize_attrs_with_lov_status) as the source of
    truth — guarantees agreement with the LOV-mismatch flag columns in Excel.
    Only counts attributes that are in the TC schema for the given class.

    Returns 0-100. If no LOV-governed TC attributes were extracted, returns 100.
    """
    schema_set = set(get_schema(part_class)) if part_class else None
    # Count LOV-governed TC attributes that were actually extracted
    lov_total = sum(
        1 for k in attributes
        if (canonical := ALIASES.get(k.strip().lower(), k.strip())) in LOV_MAP
        and attributes[k]
        and (schema_set is None or canonical in schema_set)
    )

    if lov_total == 0:
        return 100.0  # nothing to violate

    n_mismatches = len(lov_mismatches) if lov_mismatches else 0
    lov_compliant = lov_total - n_mismatches
    return round(lov_compliant / lov_total * 100, 1)


# ── Column 6: Validation Action ────────────────────────────────────────────

def get_validation_action(validation_reason: str) -> str:
    """Extract clean action label from validation reason string."""
    if not validation_reason:
        return "No validation"
    r = validation_reason.lower()
    if "reclassified" in r:
        return "Reclassified"
    if "confirmed" in r:
        return "Confirmed"
    if "refined" in r:
        return "Refined"
    if "kept" in r:
        return "Abstained"
    return "No validation"
