"""Classify a mechanical/industrial part into a standard category using an LLM."""

import json
from src.llm_client import LLMClient
from src.attr_schema import KNOWN_CLASSES


# Compact class list (comma-separated, no line breaks)
_CLASSES_STR = ", ".join(sorted(KNOWN_CLASSES))


class PartClassifier:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def classify(self, text: str) -> str:
        """Classify a single part from Part Name, scraped web content, or mfg info."""
        text = text[:600].strip()

        response = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Industrial parts classification expert. "
                        "Reply with ONLY the category name (1-4 words). No explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Classify into the MOST SPECIFIC category.\n\n"
                        f"INPUT: {text}\n\n"
                        f"EXAMPLES: "
                        f"\"WSHR, SPT LK, M20\" -> Split Lock Washer | "
                        f"\"6200ZZ 10mm bore bearing\" -> Deep Groove Ball Bearing | "
                        f"\"SS-400-1-4 Swagelok\" -> Tube Fitting | "
                        f"\"SY3120 SMC solenoid\" -> Solenoid Valve\n\n"
                        f"CATEGORIES: {_CLASSES_STR}\n\n"
                        f"RULES: Most specific match. \"Unclassified\" only as last resort."
                    ),
                },
            ],
            max_tokens=20,
            temperature=0,
        )
        return response.strip().strip('"').strip("'")

    async def classify_batch(self, parts: list[dict], batch_size: int = 50) -> dict[str, str]:
        """Classify multiple parts in a single LLM call for token efficiency.

        Args:
            parts: List of {"key": mfg_part_num, "text": classification_text}
            batch_size: Max parts per LLM call.

        Returns:
            Dict of {mfg_part_num: part_class}. Failed items mapped to "Unclassified".
        """
        results: dict[str, str] = {}

        for i in range(0, len(parts), batch_size):
            batch = parts[i:i + batch_size]
            # Build compact input
            lines = []
            for item in batch:
                key = item["key"]
                text = item["text"][:200].strip()
                lines.append(f'"{key}": "{text}"')

            input_block = "{\n" + ",\n".join(lines) + "\n}"

            try:
                response = await self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Industrial parts classification expert. "
                                "Classify each part into the most specific category. "
                                "Return ONLY valid JSON: {\"part_num\": \"Category\", ...}"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Classify each part:\n{input_block}\n\n"
                                f"CATEGORIES: {_CLASSES_STR}\n\n"
                                f"Return JSON mapping each key to its category."
                            ),
                        },
                    ],
                    max_tokens=batch_size * 15,
                    temperature=0,
                )

                # Parse response — handle partial failures
                parsed = self._parse_batch_response(response)
                for item in batch:
                    key = item["key"]
                    if key in parsed and parsed[key] and parsed[key] != "Unclassified":
                        results[key] = parsed[key]
                    else:
                        # Partial failure: classify individually
                        try:
                            cls = await self.classify(item["text"])
                            results[key] = cls
                        except Exception:
                            results[key] = "Unclassified"

            except Exception as e:
                print(f"    Batch classify failed ({e}), falling back to individual")
                for item in batch:
                    try:
                        cls = await self.classify(item["text"])
                        results[item["key"]] = cls
                    except Exception:
                        results[item["key"]] = "Unclassified"

        return results

    @staticmethod
    def _parse_batch_response(response: str) -> dict[str, str]:
        """Parse batch classification JSON response, handling malformed output."""
        response = response.strip()
        # Strip markdown fences
        if response.startswith("```"):
            response = response.split("\n", 1)[-1].rsplit("```", 1)[0]

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract partial JSON
        import re
        pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', response)
        return dict(pairs)
