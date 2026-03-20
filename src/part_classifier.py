"""Classify a mechanical/industrial part into a standard category using an LLM."""

from src.llm_client import LLMClient
from src.attr_schema import KNOWN_CLASSES


class PartClassifier:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def classify(self, text: str) -> str:
        """Classify a part from Part Name, scraped web content, or mfg info.

        The input `text` can be:
        - A short part name: "WSHR, SPT LK, M20"
        - A chunk of scraped web content describing the product
        - A fallback: "McMaster-Carr 92148A261"
        """
        # Truncate to avoid sending huge web content
        text = text[:600].strip()

        response = await self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an industrial parts classification expert.\n"
                        "You can classify parts from: part names, product descriptions, "
                        "scraped web pages, or manufacturer + part number combinations.\n"
                        "Reply with ONLY the category name (1-4 words). No explanation, no punctuation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Classify this into the MOST SPECIFIC category.\n\n"
                        f"INPUT:\n{text}\n\n"
                        f"EXAMPLES:\n"
                        f"  \"WSHR, SPT LK, M20\" → Split Lock Washer\n"
                        f"  \"WASHER, #5, INT TOOTH\" → Internal Tooth Lock Washer\n"
                        f"  \"Deep Groove Ball Bearing 6200ZZ ... 10mm bore\" → Deep Groove Ball Bearing\n"
                        f"  \"HSR20R Linear Guide Block THK ...\" → Linear Guide\n"
                        f"  \"SS-400-1-4 Swagelok Tube Fitting ...\" → Tube Fitting\n"
                        f"  \"SY3120 5 Port Solenoid Valve SMC ...\" → Solenoid Valve\n"
                        f"  \"DSNU Round Cylinder Festo ... pneumatic\" → Pneumatic Cylinder\n"
                        f"  \"E2E Proximity Sensor Omron ...\" → Proximity Sensor\n"
                        f"  \"2-012 O-Ring Parker N674 Nitrile\" → O-Ring\n\n"
                        f"Available categories:\n{', '.join(KNOWN_CLASSES)}\n\n"
                        f"RULES:\n"
                        f"- Choose the MOST SPECIFIC match\n"
                        f"- Use \"Deep Groove Ball Bearing\" not \"Ball Bearing\" when bore/OD suggests it\n"
                        f"- Use \"Solenoid Valve\" not \"Pneumatic Valve\" for electrically actuated valves\n"
                        f"- If unsure, pick the closest match from the list above\n"
                        f"- Only use \"Unclassified\" as absolute last resort"
                    ),
                },
            ],
            max_tokens=30,
        )
        return response.strip().strip('"').strip("'")
