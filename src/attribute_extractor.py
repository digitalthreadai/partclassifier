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
            "If the source provides inches, convert to mm (1 inch = 25.4 mm). "
            "If the source already provides both, use the mm values.",
        )
    else:  # default: inches
        return (
            "imperial (inches)",
            "inches",
            "All dimensional values MUST be in inches. "
            "If the source provides mm, convert to inches (1 mm = 0.03937 inches). "
            "If the source already provides both, use the inch values.",
        )


def _example_json(unit_short: str) -> str:
    if unit_short == "mm":
        return ('{"Inner Diameter": "21.2 mm", "Outer Diameter": "33.6 mm", '
                '"Thickness": "3.8 mm to 4.2 mm", "Material": "18-8 Stainless Steel", '
                '"Standard": "DIN 127B", "Hardness": "Not Rated"}')
    return ('{"Inner Diameter": "0.835 in", "Outer Diameter": "1.323 in", '
            '"Thickness": "0.150 in to 0.165 in", "Material": "18-8 Stainless Steel", '
            '"Standard": "ASME B18.21.1", "Hardness": "Not Rated"}')


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


class AttributeExtractor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def extract(self, raw_content: str, part_class: str, mfg_part_num: str,
                      part_name: str = "", unit_of_measure: str = "") -> dict[str, str]:
        """Parse raw page text and return a dict of attribute -> value."""
        truncated = raw_content[:MAX_CONTENT_CHARS]
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)

        raw = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a mechanical parts data extraction specialist. "
                        "Extract specifications and return ONLY valid JSON. No markdown, no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Part Number      : {mfg_part_num}\n"
                        f"Part Name        : {part_name}\n"
                        f"Part Class       : {part_class}\n"
                        f"Target Unit      : {unit_label}\n"
                        f"UNIT RULE        : {convert_note}\n\n"
                        f"Extract specifications from the content below.\n"
                        f"USE THESE EXACT ATTRIBUTE NAMES (where applicable): "
                        f"{', '.join(get_schema(part_class))}\n"
                        f"Rules:\n"
                        f"  - All dimensional values must be in {unit_short}\n"
                        f"  - Use the exact attribute names listed above -- do NOT invent synonyms\n"
                        f"  - Include Material, Hardness, Standard, Washer Type, System of Measurement, "
                        f"Performance if present in the source\n"
                        f"  - Omit attributes not found in the source\n\n"
                        f"Content:\n---\n{truncated}\n---\n\n"
                        f"Return ONLY a flat JSON object. "
                        f'Example ({unit_label}): {_example_json(unit_short)}'
                    ),
                },
            ],
            max_tokens=1_000,
        )

        result = _parse_json(raw)
        skip_keys = {"part number", "part name", "part no", "part #"}
        cleaned = {
            k: v for k, v in result.items()
            if k.lower() not in skip_keys
            and str(v).strip().lower() not in ("", "none", "not specified", "n/a", "unknown", "null")
        }
        return normalize_attrs(cleaned, part_class)

    async def extract_from_part_name(self, part_name: str, part_class: str,
                                     mfg_part_num: str, unit_of_measure: str = "") -> dict[str, str]:
        """Fallback: extract any dimensions encoded in the part name itself."""
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)

        raw = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "You are a mechanical parts expert. Return ONLY valid JSON. No markdown, no explanation.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Extract any dimensions or specifications encoded in this part name.\n\n"
                        f"Part Number  : {mfg_part_num}\n"
                        f"Part Class   : {part_class}\n"
                        f"Part Name    : {part_name}\n"
                        f"Target Unit  : {unit_label}\n"
                        f"UNIT RULE    : {convert_note}\n\n"
                        f"Return a JSON object with attribute names as keys and values in {unit_short}. "
                        f"Return {{}} if nothing can be extracted."
                    ),
                },
            ],
            max_tokens=500,
        )

        result = _parse_json(raw)
        return normalize_attrs(result, part_class)
