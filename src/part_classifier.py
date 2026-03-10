"""Classify a mechanical part into a standard category using an LLM."""

from src.llm_client import LLMClient

KNOWN_CLASSES = [
    "Washer", "Lock Washer", "Split Lock Washer", "Flat Washer",
    "Nut", "Lock Nut", "Hex Nut", "Wing Nut",
    "Bolt", "Hex Bolt", "Carriage Bolt",
    "Screw", "Cap Screw", "Set Screw", "Machine Screw",
    "Hook", "Eye Bolt", "Eye Hook",
    "Pin", "Cotter Pin", "Dowel Pin", "Roll Pin",
    "Rivet", "Blind Rivet",
    "Clip", "E-Clip", "C-Clip",
    "Ring", "Retaining Ring", "O-Ring",
    "Bushing", "Spacer", "Standoff",
    "Stud", "Insert", "Anchor",
    "Spring", "Compression Spring",
    "Bracket", "Fitting",
]


class PartClassifier:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def classify(self, part_name: str) -> str:
        """Return the part class/category from the part name."""
        response = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "You are a mechanical parts classification expert. Reply with only the category name, 1-4 words, no explanation.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Classify this mechanical part into a standard category.\n"
                        f"Part name: {part_name}\n\n"
                        f"Common categories: {', '.join(KNOWN_CLASSES)}"
                    ),
                },
            ],
            max_tokens=30,
        )
        return response
