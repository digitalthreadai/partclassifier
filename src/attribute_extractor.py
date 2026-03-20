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

        schema_attrs = get_schema(part_class)
        numbered_attrs = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(schema_attrs))

        raw = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a mechanical parts data extraction specialist.\n"
                        "CRITICAL RULES:\n"
                        "- Extract ONLY values that are EXPLICITLY stated in the provided content.\n"
                        "- NEVER guess, infer, calculate, or derive values that are not written in the text.\n"
                        "- If a value is not explicitly present in the content, OMIT that attribute entirely.\n"
                        "- Return ONLY valid JSON. No markdown fences, no explanation, no commentary."
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
                        f"Search the content below for EACH of these attributes, one by one:\n"
                        f"{numbered_attrs}\n\n"
                        f"Also look for: Material, Hardness, Standard, System of Measurement, "
                        f"Performance, RoHS, REACH (if present).\n\n"
                        f"EXTRACTION RULES:\n"
                        f"  1. Use the EXACT attribute names listed above — do NOT rename them\n"
                        f"  2. All dimensional values must be in {unit_short}\n"
                        f"  3. Copy values exactly as they appear — do not round or reformat\n"
                        f"  4. For ranges, use the format: \"3.8 mm to 4.2 mm\"\n"
                        f"  5. OMIT any attribute whose value is not explicitly found in the content\n\n"
                        f"EXAMPLE INPUT (mm):\n"
                        f"  Content contains: \"Inner Diameter 21.2mm ... Outer Diameter 33.6mm ... "
                        f"Thickness 3.8 to 4.2mm ... Material: 18-8 Stainless Steel ... DIN 127B\"\n"
                        f"EXAMPLE OUTPUT:\n"
                        f"  {_example_json('mm')}\n\n"
                        f"EXAMPLE INPUT (inches):\n"
                        f"  Content contains: \"Inside Diameter .835\\\" ... OD 1.323\\\" ... "
                        f"Thickness .150\\\" to .165\\\" ... 18-8 SS ... ASME B18.21.1\"\n"
                        f"EXAMPLE OUTPUT:\n"
                        f"  {_example_json('inches')}\n\n"
                        f"NOW EXTRACT FROM THIS CONTENT:\n---\n{truncated}\n---\n\n"
                        f"Return ONLY a flat JSON object."
                    ),
                },
            ],
            max_tokens=1_500,
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

        schema_attrs = get_schema(part_class)

        raw = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a mechanical parts expert who decodes abbreviated part names.\n"
                        "Return ONLY valid JSON. No markdown fences, no explanation."
                    ),
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
                        f"USE THESE EXACT ATTRIBUTE NAMES: {', '.join(schema_attrs)}\n\n"
                        f"EXAMPLES:\n"
                        f"  Part Name: \"WSHR, SPT LK, M20, 21.2 MM ID, 33.6 MM OD\"\n"
                        f"  Output: {{\"Screw Size\": \"M20\", \"Inner Diameter\": \"21.2 mm\", "
                        f"\"Outer Diameter\": \"33.6 mm\"}}\n\n"
                        f"  Part Name: \"WASHER, 1/4, 1 1/2 OD X .281 ID X .06 THK\"\n"
                        f"  Output: {{\"Screw Size\": \"1/4\", \"Inner Diameter\": \"0.281 in\", "
                        f"\"Outer Diameter\": \"1.5 in\", \"Thickness\": \"0.06 in\"}}\n\n"
                        f"Return a JSON object with values in {unit_short}. "
                        f"Return {{}} if nothing can be extracted."
                    ),
                },
            ],
            max_tokens=500,
        )

        result = _parse_json(raw)
        return normalize_attrs(result, part_class)
