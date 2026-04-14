"""Extract structured dimensions from raw product content using an LLM."""

from src.llm_client import LLMClient
from src.attr_schema import get_schema, normalize_attrs_with_lov_status, CLASS_ATTR_META, CLASS_LOV_MAP, _resolve_class_map
import json
import re

MAX_CONTENT_CHARS = 8_000


def _unit_instructions(unit_of_measure: str) -> tuple[str, str, str]:
    """Return (label, short, conversion_instruction) for the given unit."""
    u = unit_of_measure.strip().lower()
    if u == "mm":
        return (
            "metric (mm)",
            "mm",
            "All dimensional values MUST be in mm. "
            "If source provides inches, convert (1 in = 25.4 mm).",
        )
    elif u in ("inches", "in", "inch"):
        return (
            "imperial (inches)",
            "inches",
            "All dimensional values MUST be in inches. "
            "If source provides mm, convert (1 mm = 0.03937 in).",
        )
    else:
        return (
            "as-is (preserve original units)",
            "original",
            "Keep dimensional values in whatever unit they appear in the source content. "
            "Do NOT convert units. Include the unit suffix (mm, in, etc.) with each value.",
        )


def _example_json(unit_short: str) -> str:
    if unit_short == "mm":
        return ('{"Inner Diameter": "21.2 mm", "Outer Diameter": "33.6 mm", '
                '"Thickness": "3.8 mm to 4.2 mm", "Material": "18-8 Stainless Steel", '
                '"Hardness": "Rockwell C34", "Standard": "DIN 127B"}')
    elif unit_short == "original":
        return ('{"Inner Diameter": "21.2 mm", "Outer Diameter": "33.6 mm", '
                '"Thickness": "3.8 mm to 4.2 mm", "Material": "18-8 Stainless Steel", '
                '"Hardness": "Rockwell C34", "Standard": "DIN 127B"}')
    return ('{"Inner Diameter": "0.835 in", "Outer Diameter": "1.323 in", '
            '"Thickness": "0.150 in to 0.165 in", "Material": "18-8 Stainless Steel", '
            '"Hardness": "Rockwell C34", "Standard": "ASME B18.21.1"}')


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    print(f"    Could not parse JSON: {raw[:200]}")
    return {}


def _single_value(value: str, part_name: str) -> str:
    """If value contains multiple comma-separated values, pick the best one.

    Pages often list a sizing table with multiple values (e.g., ".055, .063, .078").
    We need exactly ONE value for this specific part.
    """
    parts = [v.strip() for v in value.split(",")]
    if len(parts) <= 2:
        return value  # "3.8 to 4.2" or "18-8, Stainless Steel" are fine

    # Multiple values detected — try to match against part name
    part_lower = part_name.lower()
    for p in parts:
        p_clean = p.strip().strip('"').strip("'")
        if p_clean and p_clean.lower() in part_lower:
            return p_clean

    # No match in part name — return first value
    return parts[0].strip()


def _clean_result(result: dict, part_class: str, part_name: str = "") -> tuple[dict, dict, dict, dict]:
    """Remove junk keys, enforce single values, normalize, and track transformations.

    Returns (normalized_attrs, lov_mismatches, pre_conversion_originals).
    """
    skip_keys = {"part number", "part name", "part no", "part #", "_source_url",
                  "description", "features", "overview", "product name", "category",
                  "manufacturer", "brand", "model", "series", "url", "image"}
    cleaned = {}
    for k, v in result.items():
        if k.lower() in skip_keys:
            continue
        vs = str(v).strip()
        if vs.lower() in ("", "none", "not specified", "n/a", "unknown", "null"):
            continue
        # Enforce single value per attribute
        if part_name:
            vs = _single_value(vs, part_name)
        cleaned[k] = vs
    return normalize_attrs_with_lov_status(cleaned, part_class)  # returns 4-tuple


class AttributeExtractor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def extract(self, raw_content: str, part_class: str, mfg_part_num: str,
                      part_name: str = "", unit_of_measure: str = "",
                      pre_extracted: dict[str, str] | None = None
                      ) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
        """Parse raw page text and return a 4-tuple.

        Returns:
            (attributes, lov_mismatches, pre_conversion_originals)
        """
        truncated = raw_content[:MAX_CONTENT_CHARS]
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)
        schema_attrs = get_schema(part_class)

        # Build reference context from regex pre-extraction (if available)
        reference_block = ""
        if pre_extracted and len(pre_extracted) >= 1:
            pre_json = json.dumps(pre_extracted, ensure_ascii=False)
            reference_block = (
                f"Pre-extracted values (verify, correct, and add any missing):\n"
                f"{pre_json}\n\n"
            )

        # Use only the unit-appropriate example (saves ~100 tokens)
        example = _example_json(unit_short)

        # Build priority hints from schema with type/unit/LOV context
        priority_line = ""
        if schema_attrs:
            class_attr_meta = _resolve_class_map(CLASS_ATTR_META, part_class)
            class_lov = _resolve_class_map(CLASS_LOV_MAP, part_class)
            hints = []
            for attr in schema_attrs:
                meta = class_attr_meta.get(attr, {})
                tags = []
                if meta.get("type"):
                    tags.append(meta["type"])
                if meta.get("unit"):
                    tags.append(meta["unit"])
                if meta.get("precision") is not None:
                    tags.append(f"≤{meta['precision']} decimals")
                if meta.get("type") == "lov":
                    lov_vals = class_lov.get(attr, [])
                    if lov_vals:
                        tags.append(f"LOV: {' | '.join(lov_vals[:10])}")
                hints.append(f"{attr} [{', '.join(tags)}]" if tags else attr)
            priority_line = (
                f"PRIORITY ATTRIBUTES (extract these first if present):\n"
                f"  {', '.join(hints)}\n\n"
            )

        raw = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Industrial parts data extraction specialist. "
                        "Extract ONLY explicitly stated values. Never guess or infer. "
                        "Return ONLY valid JSON. No markdown, no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Part: {mfg_part_num} | Class: {part_class} | Unit: {unit_label}\n"
                        f"UNIT RULE: {convert_note}\n\n"
                        f"{reference_block}"
                        f"{priority_line}"
                        f"Then extract ALL other specifications found in the content.\n"
                        f"Maximize coverage — extract as many attributes as possible, "
                        f"including dimensions, material, finish, hardness, tolerances, "
                        f"standards, compliance, and any other technical specifications.\n\n"
                        f"RULES:\n"
                        f"1. For priority attributes above, use those exact names.\n"
                        f"2. For other attributes, use names as they appear in the content.\n"
                        f"3. All dimensional values in {unit_short}. Convert if needed.\n"
                        f"4. Ranges: \"3.8 mm to 4.2 mm\". Omit attributes not found.\n"
                        f"5. CRITICAL: Return exactly ONE value per attribute — the value "
                        f"for THIS specific part ({mfg_part_num}). If the page lists "
                        f"multiple sizes/values, pick the one matching {mfg_part_num} "
                        f"or part name: {part_name}. Never return comma-separated lists.\n"
                        f"EXAMPLE: {example}\n\n"
                        f"CONTENT:\n---\n{truncated}\n---\n\n"
                        f"Return flat JSON object with ALL extracted attributes."
                    ),
                },
            ],
            max_tokens=1_500,
            temperature=0,
        )

        result = _parse_json(raw)
        attrs, lov_mismatches, pre_conversion_originals = _clean_result(
            result, part_class, part_name=part_name
        )

        # LLM-augmented LOV resolution: semantic matching for remaining mismatches
        if lov_mismatches:
            resolved = await self._resolve_lov_mismatches_with_llm(lov_mismatches, part_class)
            for attr, matched_val in resolved.items():
                attrs[attr] = matched_val
                lov_mismatches.pop(attr, None)

        # Validation retry: only if first attempt returned SOME data but missed
        # >50% of SCHEMA attrs (count schema hits, not total attrs)
        schema_hits = sum(1 for a in schema_attrs if a in attrs) if schema_attrs else 0
        if (schema_attrs and attrs and len(attrs) >= 1
                and schema_hits < len(schema_attrs) * 0.5 and len(truncated) >= 500):
            missing = [a for a in schema_attrs if a not in attrs]
            if missing and len(missing) <= 10:
                retry_attrs = await self._retry_missing(
                    truncated, part_class, mfg_part_num, unit_short, convert_note, missing
                )
                if retry_attrs:
                    # Clean only the new retry results (existing attrs already clean),
                    # then merge into attrs, lov_mismatches, range/fraction originals
                    new_attrs, new_mismatches, new_pre_conversion_originals = _clean_result(
                        retry_attrs, part_class, part_name=part_name
                    )
                    attrs.update(new_attrs)
                    lov_mismatches.update(new_mismatches)
                    pre_conversion_originals.update(new_pre_conversion_originals)
                    # Drop mismatches for attrs that the retry filled with a valid value
                    for k in new_attrs:
                        if k not in new_mismatches and k in lov_mismatches:
                            del lov_mismatches[k]

        return attrs, lov_mismatches, pre_conversion_originals

    async def _retry_missing(self, content: str, part_class: str, mfg_part_num: str,
                              unit_short: str, convert_note: str,
                              missing_attrs: list[str]) -> dict[str, str]:
        """Focused retry for specific missing attributes."""
        try:
            raw = await self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "Extract ONLY explicitly stated values. Return valid JSON only.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Part: {mfg_part_num} ({part_class})\n"
                            f"Find ONLY these attributes: {', '.join(missing_attrs)}\n"
                            f"Units: {unit_short}. {convert_note}\n\n"
                            f"CONTENT:\n---\n{content[:4000]}\n---\n\n"
                            f"Return JSON with found attributes only. Return {{}} if none found."
                        ),
                    },
                ],
                max_tokens=500,
                temperature=0,
            )
            result = _parse_json(raw)
            return result  # raw dict — caller (_retry_missing) handles normalization
        except Exception:
            return {}

    async def _resolve_lov_mismatches_with_llm(
        self, mismatches: dict[str, str], part_class: str
    ) -> dict[str, str]:
        """Semantic LOV resolution for values that RapidFuzz/string strategies couldn't match.

        Handles abbreviations, alternate spellings, and unit variations
        (e.g., 'SS' → 'Stainless Steel', 'HRC 34' → 'Rockwell C34').

        Returns {canonical_attr: matched_lov_value} for resolved attrs only.
        Returned values are validated against the LOV list before being accepted.
        """
        if not mismatches or len(mismatches) > 8:
            return {}

        # CLASS_LOV_MAP and _resolve_class_map imported at module level

        # Build per-attr LOV options for only the mismatched attrs
        class_lov = CLASS_LOV_MAP.get(part_class, {})
        if not class_lov:
            lower = part_class.lower()
            for cls_key, lov_map in CLASS_LOV_MAP.items():
                if cls_key.lower() == lower or cls_key.lower() in lower or lower in cls_key.lower():
                    class_lov = lov_map
                    break

        attr_options: dict[str, dict] = {}
        for attr, value in mismatches.items():
            lov_values = class_lov.get(attr)
            if lov_values:
                attr_options[attr] = {"value": value, "options": lov_values}

        if not attr_options:
            return {}

        prompt_data = json.dumps(attr_options, ensure_ascii=False)
        try:
            raw = await self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Industrial parts data normalization expert. "
                            "Match extracted values to valid list-of-values (LOV) options. "
                            "Account for abbreviations, alternate spellings, unit variations. "
                            "Return ONLY valid JSON, no explanation."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"For each attribute, determine if the extracted value semantically "
                            f"matches any valid option. Examples: 'SS'→'Stainless Steel', "
                            f"'HRC 34'→'Rockwell C34', 'A2-70'→'Grade A2'.\n\n"
                            f"Input: {prompt_data}\n\n"
                            f"Return JSON: {{\"attr_name\": \"matched_option\"}} for matches only. "
                            f"Omit attributes with no genuine match. "
                            f"The returned value MUST be one of the provided options exactly."
                        ),
                    },
                ],
                max_tokens=300,
                temperature=0,
            )
            result = _parse_json(raw)
            # Validate: accepted value must be an exact LOV entry
            resolved: dict[str, str] = {}
            for attr, matched_val in result.items():
                if attr in attr_options and matched_val in attr_options[attr]["options"]:
                    resolved[attr] = matched_val
            if resolved:
                print(f"    LOV-LLM: resolved {len(resolved)} mismatch(es): {list(resolved.keys())}")
            return resolved
        except Exception:
            return {}

    async def extract_from_part_name(self, part_name: str, part_class: str,
                                     mfg_part_num: str, unit_of_measure: str = ""
                                     ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """Fallback: extract any dimensions encoded in the part name itself.

        Returns (attributes, lov_mismatches, pre_conversion_originals).
        """
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)
        schema_attrs = get_schema(part_class)

        raw = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Industrial parts classification specialist. Decode abbreviated part names and identifiers. Return valid JSON only.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Extract dimensions from this part name.\n\n"
                        f"Part: {mfg_part_num} | Class: {part_class} | Name: {part_name}\n"
                        f"Unit: {unit_label}. {convert_note}\n"
                        f"Attributes: {', '.join(schema_attrs)}\n\n"
                        f"EXAMPLE: \"WSHR, SPT LK, M20, 21.2 MM ID\" -> "
                        f"{{\"Screw Size\": \"M20\", \"Inner Diameter\": \"21.2 mm\"}}\n\n"
                        f"Return JSON in {unit_short}. Return {{}} if nothing extractable."
                    ),
                },
            ],
            max_tokens=500,
            temperature=0,
        )

        result = _parse_json(raw)
        return normalize_attrs_with_lov_status(result, part_class)  # returns 4-tuple
