"""
Part Classification Agent
=========================
For each part in the input Excel:
  1. Classify it (LLM) using the Part Name.
  2. Search the web for the Manufacturer Part Number and scrape the product page.
  3. Extract all dimensions / attributes (LLM).
  4. Write one output Excel per class into the output/ folder.

Usage:
    python main.py

Prerequisites:
    Copy .env.example to .env and configure LLM provider + API key.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR   = Path(__file__).parent
EXCEL_PATH = BASE_DIR / "input" / "PartClassifierInput.xlsx"
OUTPUT_DIR = BASE_DIR / "output"


# -- Per-part processing ---------------------------------------------------

async def process_part(
    part: dict,
    scraper,
    classifier,
    attr_extractor,
) -> dict:
    mfg_part_num     = str(part.get("Manufacturer Part Number") or "").strip()
    mfg_name         = str(part.get("Manufacturer Name")        or "").strip()
    part_name        = str(part.get("Part Name")                or "").strip()
    unit_of_measure  = str(part.get("Unit of Measure")          or "inches").strip().lower()

    print(f"\n{'-'*60}")
    print(f"  Part #  : {mfg_part_num}")
    print(f"  Name    : {part_name}")
    print(f"  Maker   : {mfg_name}")
    print(f"  Unit    : {unit_of_measure}")

    # 1 -- Classify
    part_class = await classifier.classify(part_name)
    print(f"  Class   : {part_class}")

    # 2 -- Find product page and scrape
    print(f"  Searching: {mfg_name} {mfg_part_num} ...")
    raw_content, source_url = await scraper.find_and_scrape(mfg_name, mfg_part_num, unit_of_measure)

    if raw_content:
        print(f"  Content : {len(raw_content):,} chars")
    else:
        print(f"  Content : not found - falling back to part name")

    # 3 -- Extract attributes
    if raw_content:
        attributes = await attr_extractor.extract(
            raw_content, part_class, mfg_part_num, part_name, unit_of_measure
        )
    else:
        # Fallback: mine dimensions from the part name itself
        source_url = "part name"
        attributes = await attr_extractor.extract_from_part_name(
            part_name, part_class, mfg_part_num, unit_of_measure
        )

    if attributes:
        print(f"  Attrs ({len(attributes)}):")
        for k, v in attributes.items():
            print(f"    {k}: {v}")
    else:
        print(f"  Attrs   : (none found)")

    return {
        "part":       part,
        "part_class": part_class,
        "attributes": attributes,
        "source_url": source_url or "",
    }


# -- Main ------------------------------------------------------------------

async def main() -> None:
    if not EXCEL_PATH.exists():
        print(f"ERROR: {EXCEL_PATH} not found")
        sys.exit(1)

    from src.llm_client         import LLMClient
    from src.excel_handler      import ExcelHandler
    from src.part_classifier    import PartClassifier
    from src.web_scraper        import WebScraper
    from src.attribute_extractor import AttributeExtractor

    try:
        llm = LLMClient()
    except (ValueError, ImportError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    handler        = ExcelHandler(str(EXCEL_PATH), str(OUTPUT_DIR))
    classifier     = PartClassifier(llm)
    attr_extractor = AttributeExtractor(llm)

    parts = handler.read_parts()

    print(f"\nPart Classification Agent")
    print(f"{'='*60}")
    print(f"  Input  : {EXCEL_PATH.name}  ({len(parts)} parts)")
    print(f"  Output : {OUTPUT_DIR}/")
    print(f"  Model  : {llm.display_name()}")

    results: list[dict] = []
    async with WebScraper() as scraper:
        for part in parts:
            result = await process_part(part, scraper, classifier, attr_extractor)
            results.append(result)

    print(f"\n{'='*60}")
    print("Writing output files...")
    written = handler.write_class_files(results)
    for path in written:
        print(f"  -> {path}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
