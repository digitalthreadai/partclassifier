"""Extract structured dimensions from raw product content using an LLM."""

from src.llm_client import LLMClient
from src.attr_schema import get_schema, normalize_attrs
import json
import re

MAX_CONTENT_CHARS = 8_000


def _unit_instructions(unit_of_measure: str) -> tuple[str, str, str]:
    """Return (label, short, conversion_instruction) for the given unit."""
    if unit_of_measure.strip().lower() == "mm":
        return (
            "metric (mm)",
            "mm",
            "All dimensional values MUST be in mm. "
            "If source provides inches, convert (1 in = 25.4 mm).",
        )
    else:
        return (
            "imperial (inches)",
            "inches",
            "All dimensional values MUST be in inches. "
            "If source provides mm, convert (1 mm = 0.03937 in).",
        )


def _example_json(unit_short: str) -> str:
    if unit_short == "mm":
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


def _clean_result(result: dict, part_class: str) -> dict:
    """Remove junk keys and normalize."""
    skip_keys = {"part number", "part name", "part no", "part #", "_source_url",
                  "description", "features", "overview", "product name", "category",
                  "manufacturer", "brand", "model", "series", "url", "image"}
    cleaned = {
        k: v for k, v in result.items()
        if k.lower() not in skip_keys
        and str(v).strip().lower() not in ("", "none", "not specified", "n/a", "unknown", "null")
    }
    return normalize_attrs(cleaned, part_class)


class AttributeExtractor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def extract(self, raw_content: str, part_class: str, mfg_part_num: str,
                      part_name: str = "", unit_of_measure: str = "",
                      pre_extracted: dict[str, str] | None = None) -> dict[str, str]:
        """Parse raw page text and return a dict of attribute -> value.

        Args:
            pre_extracted: Optional regex-extracted values for LLM to validate/augment.
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

        # Build priority hints from schema (focus + breadth)
        priority_line = ""
        if schema_attrs:
            priority_line = (
                f"PRIORITY ATTRIBUTES (extract these first if present):\n"
                f"  {', '.join(schema_attrs)}\n\n"
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
        attrs = _clean_result(result, part_class)

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
                    attrs.update(retry_attrs)

        return attrs

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
            return _clean_result(result, part_class)
        except Exception:
            return {}

    async def extract_from_part_name(self, part_name: str, part_class: str,
                                     mfg_part_num: str, unit_of_measure: str = "") -> dict[str, str]:
        """Fallback: extract any dimensions encoded in the part name itself."""
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)
        schema_attrs = get_schema(part_class)

        raw = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Mechanical parts expert. Decode abbreviated part names. Return valid JSON only.",
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
        return normalize_attrs(result, part_class)
