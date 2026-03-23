"""
Part Classification Agent
=========================
For each part in the input Excel:
  1. Search the web for the Manufacturer Part Number and scrape the product page.
  2. Classify the part from scraped web content (or Part Name if available).
  3. Pre-extract attributes via regex, then validate/fill with LLM.
  4. Write one output Excel per class into the output/ folder.

Usage:
    python main.py
    python main.py --input path/to/input.xlsx --output path/to/output/
    python main.py --no-cache       # ignore LLM cache
    python main.py --clear-cache    # delete cache before run

Prerequisites:
    Copy .env.example to .env and configure LLM provider + API key.
"""

import asyncio
import io
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Fix Windows console encoding — allow Unicode chars from scraped content
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent


def _get_arg(flag: str, default: str) -> str:
    for i, arg in enumerate(sys.argv):
        if arg == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _has_flag(flag: str) -> bool:
    return flag in sys.argv


EXCEL_PATH = Path(_get_arg("--input", str(BASE_DIR / "input" / "PartClassifierInput.xlsx")))
OUTPUT_DIR = Path(_get_arg("--output", str(BASE_DIR / "output")))
NO_CACHE = _has_flag("--no-cache")
CLEAR_CACHE = _has_flag("--clear-cache")

MAX_RETRIES = 3
RETRY_DELAY = 5


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
                await asyncio.sleep(wait)
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
    llm_cache=None,
    metrics=None,
) -> dict:
    from src.class_extractor import extract_class_from_content
    from src.regex_extractor import regex_extract, compute_agreement
    from src.attr_schema import normalize_attrs, get_tc_class_id
    from src.shared import save_cache
    from src.web_scraper import _CACHE_PATH

    mfg_part_num    = str(part.get("Manufacturer Part Number") or "").strip()
    mfg_name        = str(part.get("Manufacturer Name")        or "").strip()
    part_name       = str(part.get("Part Name")                or "").strip()
    unit_of_measure = str(part.get("Unit of Measure")          or "inches").strip().lower()

    print(f"\n{'-'*60}")
    print(f"  Part #  : {mfg_part_num}")
    print(f"  Name    : {part_name}")
    print(f"  Maker   : {mfg_name}")
    print(f"  Unit    : {unit_of_measure}")

    # STEP 1 — Search the web FIRST (before classification)
    print(f"  Searching: {mfg_name} {mfg_part_num} ...")
    result = await scraper.find_and_scrape(mfg_name, mfg_part_num, unit_of_measure)

    # STEP 2 — Classify: try deterministic extraction from web content first
    part_class = None
    classify_text = part_name or (result.content[:500] if result.content else f"{mfg_name} {mfg_part_num}")

    # Try pattern matching on scraped content (no LLM needed)
    if result.content and len(result.content) >= 100:
        part_class = extract_class_from_content(
            result.content, result.source_url or "",
            mfg_name=mfg_name, mfg_part_num=mfg_part_num,
        )
        if part_class:
            print(f"  Class   : {part_class}  (from web content)")

    # Try LLM cache
    if not part_class and llm_cache:
        classify_text = part_name or (result.content[:500] if result.content else f"{mfg_name} {mfg_part_num}")
        cached_class = llm_cache.get_classification(classify_text)
        if cached_class:
            part_class = cached_class
            print(f"  Class   : {part_class}  (cached)")
            if metrics:
                metrics.record_cache_hit("classify")

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
        if metrics:
            metrics.record_llm_call("classify")
        # Cache the classification
        if llm_cache and part_class != "Unclassified":
            llm_cache.set_classification(classify_text, part_class)

    # STEP 3 — Regex pre-extraction
    pre_extracted: dict[str, str] = {}
    tables = getattr(result, "tables", None)
    if result.content:
        pre_extracted = regex_extract(result.content, part_class, tables)
        if pre_extracted:
            print(f"  Regex   : {len(pre_extracted)} attrs pre-extracted")
            if metrics:
                metrics.record_regex(len(pre_extracted))

    # STEP 4 — Extract attributes
    attributes = {}
    source_url = ""

    if result.attributes and len(result.attributes) >= 3:
        # Structured API data — normalize and skip LLM extraction
        attributes = normalize_attrs(result.attributes, part_class)
        source_url = result.source_url
        print(f"  Source   : {result.source_name}")
    elif result.content:
        # Check extraction cache
        cached_attrs = None
        if llm_cache:
            cached_attrs = llm_cache.get_extraction(mfg_part_num, part_class, result.content)
        if cached_attrs:
            attributes = cached_attrs
            source_url = result.source_url
            print(f"  Attrs   : {len(attributes)} (cached)")
            if metrics:
                metrics.record_cache_hit("extract")
        else:
            print(f"  Content : {len(result.content):,} chars")
            extracted = await _retry_llm(
                lambda: attr_extractor.extract(
                    result.content, part_class, mfg_part_num,
                    part_name or classify_text, unit_of_measure,
                    pre_extracted=pre_extracted if pre_extracted else None,
                ),
                "Extract"
            )
            attributes = extracted or {}
            source_url = result.source_url
            if metrics:
                metrics.record_llm_call("extract")
            # Log regex/LLM agreement
            if pre_extracted and attributes and metrics:
                agreement = compute_agreement(pre_extracted, attributes)
                metrics.record_regex(0, agreement)  # 0 = don't double-count
            # Cache extraction
            if llm_cache and attributes and result.content:
                llm_cache.set_extraction(mfg_part_num, part_class, result.content, attributes)
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
        if metrics:
            metrics.record_llm_call("extract")

    if attributes:
        print(f"  Attrs ({len(attributes)}):")
        for k, v in attributes.items():
            print(f"    {k}: {v}")
    else:
        print(f"  Attrs   : (none found)")
        # Evict cached URL that produced nothing — next run will try fresh search
        if result.source_url and mfg_part_num in scraper._cache:
            del scraper._cache[mfg_part_num]
            save_cache(scraper._cache, _CACHE_PATH)
            print(f"    Evicted bad cache: {result.source_url[:60]}")

    if metrics:
        metrics.record_part(
            classified=(part_class not in ("Unclassified", "Error")),
            attr_count=len(attributes),
        )

    return {
        "part":         part,
        "part_class":   part_class,
        "tc_class_id":  get_tc_class_id(part_class),
        "attributes":   attributes,
        "source_url":   source_url or "",
    }


# -- Main ------------------------------------------------------------------

async def main() -> None:
    if not EXCEL_PATH.exists():
        print(f"ERROR: {EXCEL_PATH} not found")
        sys.exit(1)

    from src.llm_client          import LLMClient
    from src.excel_handler       import ExcelHandler
    from src.part_classifier     import PartClassifier
    from src.web_scraper         import WebScraper
    from src.attribute_extractor import AttributeExtractor
    from src.shared              import rotate_manufacturers, _atomic_write_json
    from src.llm_cache           import LLMCache
    from src.metrics             import RunMetrics

    try:
        llm = LLMClient()
    except (ValueError, ImportError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    handler        = ExcelHandler(str(EXCEL_PATH), str(OUTPUT_DIR))
    classifier     = PartClassifier(llm)
    attr_extractor = AttributeExtractor(llm)
    run_metrics    = RunMetrics()

    # LLM cache setup
    cache_path = BASE_DIR / "llm_cache.json"
    llm_cache = None
    if not NO_CACHE:
        if CLEAR_CACHE and cache_path.exists():
            cache_path.unlink()
            print("  Cache cleared.")
        llm_cache = LLMCache(cache_path)
        stats = llm_cache.stats()
        if stats["classify_entries"] or stats["extract_entries"]:
            print(f"  Cache  : {stats['classify_entries']} classify, {stats['extract_entries']} extract entries")

    parts = rotate_manufacturers(handler.read_parts())

    print(f"\nPart Classification Agent")
    print(f"{'='*60}")
    print(f"  Input  : {EXCEL_PATH.name}  ({len(parts)} parts)")
    print(f"  Output : {OUTPUT_DIR}/")
    print(f"  Model  : {llm.display_name()}")
    print(f"  Cache  : {'disabled' if NO_CACHE else 'enabled'}")

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

    SAVE_EVERY = 25  # Batch progress saves to reduce I/O

    def _save_progress():
        """Atomic batch save of progress to disk."""
        _atomic_write_json(prev_progress, progress_file)

    async with WebScraper() as scraper:
        for i, part in enumerate(parts, 1):
            mfg_pn = str(part.get("Manufacturer Part Number") or "").strip()
            progress_key = f"{i}_{mfg_pn}"  # Composite key handles duplicate MPNs

            # Skip already-completed parts (resume)
            if progress_key in prev_progress:
                continue

            try:
                result = await process_part(
                    part, scraper, classifier, attr_extractor,
                    llm_cache=llm_cache, metrics=run_metrics,
                )
                results.append(result)
                completed += 1
                prev_progress[progress_key] = result

                # Batch save: write progress every SAVE_EVERY parts + Excel every 10
                if completed % SAVE_EVERY == 0:
                    _save_progress()
                if completed % 10 == 0:
                    handler.write_class_files(results)
                    print(f"\n  [{completed}/{len(parts)}] Progress saved + Excel updated")

            except Exception as e:
                print(f"\n  ERROR processing {mfg_pn}: {type(e).__name__}: {e}")
                error_result = {
                    "part": part,
                    "part_class": "Error",
                    "attributes": {},
                    "source_url": str(e)[:200],
                }
                results.append(error_result)
                prev_progress[progress_key] = error_result

        # Final save on exit
        _save_progress()

    # Print metrics and save history
    run_metrics.print_summary()
    run_metrics.save_to_history(BASE_DIR / "metrics_history.json")

    print(f"\n{'='*60}")
    print("Writing final output files...")
    written = handler.write_class_files(results)
    for path in written:
        print(f"  -> {path}")
    print(f"Done. {completed} parts processed.")


if __name__ == "__main__":
    asyncio.run(main())
