"""Classify a mechanical part into a standard category using GitHub Models."""

from openai import AsyncOpenAI

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

GROQ_URL = "https://api.groq.com/openai/v1"
MODEL = "llama-3.3-70b-versatile"


class PartClassifier:
    def __init__(self, token: str):
        self.client = AsyncOpenAI(
            base_url=GROQ_URL,
            api_key=token,
        )

    async def classify(self, part_name: str) -> str:
        """Return the part class/category from the part name."""
        response = await self.client.chat.completions.create(
            model=MODEL,
            max_tokens=30,
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
        )
        return response.choices[0].message.content.strip()
