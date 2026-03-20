"""
Part Classification Agent
=========================
For each part in the input Excel:
  1. Search the web for the Manufacturer Part Number and scrape the product page.
  2. Classify the part from scraped web content (or Part Name if available).
  3. Extract all dimensions / attributes (LLM).
  4. Write one output Excel per class into the output/ folder.

Usage:
    python main.py
    python main.py --input path/to/input.xlsx --output path/to/output/

Prerequisites:
    Copy .env.example to .env and configure LLM provider + API key.
"""

import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR   = Path(__file__).parent

def _get_arg(flag: str, default: str) -> str:
    for i, arg in enumerate(sys.argv):
        if arg == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

EXCEL_PATH = Path(_get_arg("--input", str(BASE_DIR / "input" / "PartClassifierInput.xlsx")))
OUTPUT_DIR = Path(_get_arg("--output", str(BASE_DIR / "output")))


def _rotate_manufacturers(parts: list[dict]) -> list[dict]:
    """Reorder parts so same-manufacturer parts aren't adjacent.

    Round-robin interleave by manufacturer name to space out requests
    to the same site (reduces bot detection risk).
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for p in parts:
        mfg = str(p.get("Manufacturer Name") or "").strip().upper()
        buckets[mfg].append(p)

    # Sort buckets largest-first so the most common manufacturer gets spread widest
    sorted_buckets = sorted(buckets.values(), key=len, reverse=True)

    rotated: list[dict] = []
    while any(sorted_buckets):
        for bucket in sorted_buckets:
            if bucket:
                rotated.append(bucket.pop(0))
        sorted_buckets = [b for b in sorted_buckets if b]

    return rotated


MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


async def _retry_llm(coro_fn, label: str):
    """Retry an async LLM call up to MAX_RETRIES times on timeout/transient errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await coro_fn()
        except Exception as e:
            err_name = type(e).__name__
            if attempt < MAX_RETRIES and ("timeout" in str(e).lower() or "rate" in str(e).lower()
                                          or "503" in str(e) or "429" in str(e)):
                wait = RETRY_DELAY * attempt
                print(f"    {label} {err_name} (attempt {attempt}/{MAX_RETRIES}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"    {label} failed: {err_name}: {e}")
                return None
    return None


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

    # STEP 1 — Search the web FIRST (before classification)
    print(f"  Searching: {mfg_name} {mfg_part_num} ...")
    result = await scraper.find_and_scrape(mfg_name, mfg_part_num, unit_of_measure)

    # STEP 2 — Classify: try deterministic extraction from web content first
    from src.class_extractor import extract_class_from_content

    part_class = None

    # Try pattern matching on scraped content (no LLM needed)
    if result.content and len(result.content) >= 100:
        part_class = extract_class_from_content(result.content, result.source_url or "")
        if part_class:
            print(f"  Class   : {part_class}  (from web content)")

    # Fall back to LLM classification
    if not part_class:
        if part_name:
            classify_text = part_name
        elif result.content and len(result.content) >= 200:
            classify_text = result.content[:500]
        else:
            classify_text = f"{mfg_name} {mfg_part_num}"

        part_class = await _retry_llm(
            lambda: classifier.classify(classify_text),
            "Classify"
        )
        if not part_class:
            part_class = "Unclassified"
        print(f"  Class   : {part_class}  (LLM)")

    # STEP 3 — Extract attributes
    attributes = {}
    source_url = ""

    if result.attributes and len(result.attributes) >= 3:
        # Structured API data — normalize and skip LLM extraction
        from src.attr_schema import normalize_attrs
        attributes = normalize_attrs(result.attributes, part_class)
        source_url = result.source_url
        print(f"  Source   : {result.source_name}")
    elif result.content:
        print(f"  Content : {len(result.content):,} chars")
        extracted = await _retry_llm(
            lambda: attr_extractor.extract(
                result.content, part_class, mfg_part_num,
                part_name or classify_text, unit_of_measure
            ),
            "Extract"
        )
        attributes = extracted or {}
        source_url = result.source_url
    else:
        # Fallback: mine dimensions from the part name / mfg info
        print(f"  Content : not found - falling back to part name")
        source_url = "part name"
        extracted = await _retry_llm(
            lambda: attr_extractor.extract_from_part_name(
                part_name or f"{mfg_name} {mfg_part_num}",
                part_class, mfg_part_num, unit_of_measure
            ),
            "ExtractFromName"
        )
        attributes = extracted or {}

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

    parts = _rotate_manufacturers(handler.read_parts())

    print(f"\nPart Classification Agent")
    print(f"{'='*60}")
    print(f"  Input  : {EXCEL_PATH.name}  ({len(parts)} parts)")
    print(f"  Output : {OUTPUT_DIR}/")
    print(f"  Model  : {llm.display_name()}")

    # Load previous progress for resume capability
    progress_file = OUTPUT_DIR / "progress.json"
    prev_progress = {}
    if progress_file.exists():
        try:
            prev_progress = json.loads(progress_file.read_text(encoding="utf-8"))
            print(f"  Resuming : {len(prev_progress)} parts already done")
        except Exception:
            pass

    results: list[dict] = list(prev_progress.values())
    completed = len(prev_progress)

    async with WebScraper() as scraper:
        for i, part in enumerate(parts, 1):
            mfg_pn = str(part.get("Manufacturer Part Number") or "").strip()

            # Skip already-completed parts (resume)
            if mfg_pn in prev_progress:
                continue

            try:
                result = await process_part(part, scraper, classifier, attr_extractor)
                results.append(result)
                completed += 1

                # Save progress after each part
                prev_progress[mfg_pn] = result
                progress_file.write_text(
                    json.dumps(prev_progress, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )

                # Write Excel output every 10 parts
                if completed % 10 == 0:
                    handler.write_class_files(results)
                    print(f"\n  [{completed}/{len(parts)}] Progress saved + Excel updated")

            except Exception as e:
                print(f"\n  ERROR processing {mfg_pn}: {type(e).__name__}: {e}")
                # Record error but continue
                error_result = {
                    "part": part,
                    "part_class": "Error",
                    "attributes": {},
                    "source_url": f"error: {e}",
                }
                results.append(error_result)
                prev_progress[mfg_pn] = error_result
                progress_file.write_text(
                    json.dumps(prev_progress, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )

    print(f"\n{'='*60}")
    print("Writing final output files...")
    written = handler.write_class_files(results)
    for path in written:
        print(f"  -> {path}")
    print(f"Done. {completed} parts processed.")


if __name__ == "__main__":
    asyncio.run(main())
