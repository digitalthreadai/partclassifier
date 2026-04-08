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
    python main.py --fresh          # delete cache + progress, start fresh

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


import os

EXCEL_PATH = Path(_get_arg("--input", str(BASE_DIR / "input" / "PartClassifierInput.xlsx")))
_ts = __import__("datetime").datetime.now().strftime("%m%d%Y%H%M")
OUTPUT_DIR = Path(_get_arg("--output", str(BASE_DIR / f"output-{_ts}")))
NO_CACHE = _has_flag("--no-cache")
CLEAR_CACHE = _has_flag("--clear-cache")
FRESH = _has_flag("--fresh")
# Optional post-processing: deduplicate agent-extracted columns via LLM
# Set POST_PROCESS_DEDUP=true in .env to enable
POST_PROCESS_DEDUP = os.getenv("POST_PROCESS_DEDUP", "false").lower() in ("true", "1", "yes")

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
    from src.attr_schema import normalize_attrs_with_lov_status, get_tc_class_id, map_to_json_class
    from src.shared import save_cache
    from src.web_scraper import _CACHE_PATH
    from src.file_extractor import find_spec_file, extract_from_file

    mfg_part_num    = str(part.get("Manufacturer Part Number") or "").strip()
    mfg_name        = str(part.get("Manufacturer Name")        or "").strip()
    part_name       = str(part.get("Part Name")                or "").strip()
    unit_of_measure = str(part.get("Unit of Measure")          or "").strip().lower()
    part_number     = str(part.get("Part Number")              or "").strip()

    print(f"\n{'-'*60}")
    print(f"  Part #  : {mfg_part_num}")
    print(f"  Name    : {part_name}")
    print(f"  Maker   : {mfg_name}")
    print(f"  Unit    : {unit_of_measure}")

    # STEP 0 — File Content Search (Tier 0, runs BEFORE web/API)
    # File-extracted attributes are AUTHORITATIVE — they cannot be overridden by web.
    file_result = None
    file_attrs: dict[str, str] = {}
    file_lov_mismatches: dict[str, str] = {}
    file_range_originals: dict[str, str] = {}
    spec_file = find_spec_file(part_number, mfg_part_num)
    if spec_file:
        print(f"  Spec file: {spec_file.name}")
        file_result = await extract_from_file(spec_file, classifier.llm)

    # STEP 1 — Search the web (always — file content + web are merged later)
    print(f"  Searching: {mfg_name} {mfg_part_num} ...")
    result = await scraper.find_and_scrape(mfg_name, mfg_part_num, unit_of_measure)

    # STEP 2 — Classify
    # Prefer file content for classification (more authoritative than web)
    part_class = None
    classify_source = "fallback"

    # Build classify content: file content takes priority over web content
    classify_content = (file_result.content if file_result and file_result.content
                        else result.content)
    classify_text = part_name or (classify_content[:500] if classify_content
                                  else f"{mfg_name} {mfg_part_num}")

    # Try pattern matching on content (file or web), no LLM needed
    if classify_content and len(classify_content) >= 100:
        part_class = extract_class_from_content(
            classify_content,
            (file_result.source_url if file_result else result.source_url) or "",
            mfg_name=mfg_name, mfg_part_num=mfg_part_num,
        )
        if part_class:
            classify_source = "web_high"
            src_label = "spec file" if file_result else "web content"
            print(f"  Class   : {part_class}  (from {src_label})")

    # Try LLM cache
    if not part_class and llm_cache:
        # Prefer spec file content over web content for cache key
        classify_text = (part_name
                         or (file_result.content[:500] if file_result and file_result.content else "")
                         or (result.content[:500] if result.content else "")
                         or f"{mfg_name} {mfg_part_num}")
        cached_class = llm_cache.get_classification(classify_text)
        if cached_class:
            part_class = cached_class
            classify_source = "cache"
            print(f"  Class   : {part_class}  (cached)")
            if metrics:
                metrics.record_cache_hit("classify")

    # Fall back to LLM classification
    if not part_class:
        if part_name:
            classify_text = part_name
        elif file_result and file_result.content:
            # Spec file content is more authoritative than web for classification
            classify_text = file_result.content[:500]
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
        classify_source = "llm"
        print(f"  Class   : {part_class}  (LLM)")
        if metrics:
            metrics.record_llm_call("classify")
        # Cache the classification
        if llm_cache and part_class != "Unclassified":
            llm_cache.set_classification(classify_text, part_class)

    # Map classification to Classes.json hierarchy (strict Teamcenter alignment)
    original_class = part_class
    part_class, in_json = map_to_json_class(part_class)
    if part_class != original_class:
        print(f"  Mapped  : {original_class} -> {part_class} (JSON)")

    # STEP 3 — Validate classification via class-blind attribute extraction
    from src.class_validator import blind_extract, validate_classification
    validation_reason = ""
    if classify_content and part_class not in ("Unclassified", "Error"):
        blind_attrs = await blind_extract(classifier.llm, classify_content)
        if blind_attrs:
            print(f"  Blind   : {len(blind_attrs)} attrs extracted")
            validated, validation_reason = validate_classification(part_class, blind_attrs, part_name)
            if validated != part_class:
                print(f"  Validate: {part_class} -> {validated} ({validation_reason})")
                part_class = validated
            else:
                print(f"  Validate: {part_class} {validation_reason}")

    # STEP 3b — Extract from spec file (Tier 0, AUTHORITATIVE — never overridden)
    if file_result and file_result.content:
        print(f"  File    : extracting from spec file...")
        try:
            file_extracted = await _retry_llm(
                lambda: attr_extractor.extract(
                    file_result.content, part_class, mfg_part_num,
                    part_name or classify_text, unit_of_measure,
                    pre_extracted=None,
                ),
                "ExtractFromFile"
            )
            if file_extracted:
                file_attrs, file_lov_mismatches, file_range_originals = file_extracted
                print(f"  File    : extracted {len(file_attrs)} attrs (locked, will not be overridden)")
            if metrics:
                metrics.record_llm_call("extract")
        except Exception as e:
            print(f"  File    : extraction error (skipping spec file attrs): {e}")

    # STEP 3c — Regex pre-extraction (from web content)
    pre_extracted: dict[str, str] = {}
    tables = getattr(result, "tables", None)
    if result.content:
        pre_extracted = regex_extract(result.content, part_class, tables)
        if pre_extracted:
            print(f"  Regex   : {len(pre_extracted)} attrs pre-extracted")
            if metrics:
                metrics.record_regex(len(pre_extracted))

    # STEP 4 — Extract attributes from web/API (gap-filling only if file_attrs exist)
    attributes: dict[str, str] = {}
    lov_mismatches: dict[str, str] = {}
    range_originals: dict[str, str] = {}
    source_url = ""
    regex_agreement = None

    if result.attributes and len(result.attributes) >= 3:
        # Structured API data — normalize and skip LLM extraction
        attributes, lov_mismatches, range_originals = normalize_attrs_with_lov_status(result.attributes, part_class)
        source_url = result.source_url
        print(f"  Source   : {result.source_name}")
    elif result.content:
        # Check extraction cache
        cached_attrs = None
        if llm_cache:
            cached_attrs = llm_cache.get_extraction(mfg_part_num, part_class, result.content)
        if cached_attrs:
            # Cached attrs are already normalized; re-run LOV check for mismatches
            attributes, lov_mismatches, range_originals = normalize_attrs_with_lov_status(cached_attrs, part_class)
            source_url = result.source_url
            print(f"  Attrs   : {len(attributes)} (cached)")
            if metrics:
                metrics.record_cache_hit("extract")
        else:
            print(f"  Content : {len(result.content):,} chars")
            try:
                extracted = await _retry_llm(
                    lambda: attr_extractor.extract(
                        result.content, part_class, mfg_part_num,
                        part_name or classify_text, unit_of_measure,
                        pre_extracted=pre_extracted if pre_extracted else None,
                    ),
                    "Extract"
                )
                if extracted:
                    attributes, lov_mismatches, range_originals = extracted
            except Exception as e:
                print(f"  Extract : error (continuing with empty attrs): {e}")
            source_url = result.source_url
            if metrics:
                metrics.record_llm_call("extract")
            # Log regex/LLM agreement
            if pre_extracted and attributes:
                regex_agreement = compute_agreement(pre_extracted, attributes)
                if metrics:
                    metrics.record_regex(0, regex_agreement)  # 0 = don't double-count
            # Cache extraction
            if llm_cache and attributes and result.content:
                llm_cache.set_extraction(mfg_part_num, part_class, result.content, attributes)

        # Secondary fallback: web extraction returned empty but Part Name has dimensions
        if not attributes and part_name and len(part_name) > 10:
            print(f"  Falling back to part name extraction...")
            name_extracted = await _retry_llm(
                lambda: attr_extractor.extract_from_part_name(
                    part_name, part_class, mfg_part_num, unit_of_measure
                ),
                "ExtractFromName"
            )
            if name_extracted:
                attributes, lov_mismatches, range_originals = name_extracted
                source_url = "part name (fallback)"
                print(f"  Part name extracted {len(attributes)} attrs")
            if metrics:
                metrics.record_llm_call("extract")
    else:
        # Fallback: mine dimensions from the part name / mfg info
        print(f"  Content : not found - falling back to part name")
        source_url = "part name"
        name_extracted = await _retry_llm(
            lambda: attr_extractor.extract_from_part_name(
                part_name or f"{mfg_name} {mfg_part_num}",
                part_class, mfg_part_num, unit_of_measure
            ),
            "ExtractFromName"
        )
        if name_extracted:
            attributes, lov_mismatches, range_originals = name_extracted
        if metrics:
            metrics.record_llm_call("extract")

    # STEP 4b — Merge: file_attrs ALWAYS WIN over web/API attributes
    # (file is the authoritative source, web only fills gaps)
    if file_attrs:
        merged: dict[str, str] = {}
        merged.update(attributes)       # Start with web/API attrs
        merged.update(file_attrs)       # File attrs overwrite (winning)
        attributes = merged

        # Merge LOV mismatches similarly (file mismatches win)
        merged_mismatches: dict[str, str] = {}
        merged_mismatches.update(lov_mismatches)
        merged_mismatches.update(file_lov_mismatches)
        lov_mismatches = merged_mismatches

        # Merge range originals (file wins)
        merged_ranges: dict[str, str] = {}
        merged_ranges.update(range_originals)
        merged_ranges.update(file_range_originals)
        range_originals = merged_ranges

        # If file extraction provided most of the data, prefer file as source
        if len(file_attrs) >= len(attributes) * 0.5:
            source_url = file_result.source_url if file_result else source_url

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

    # Compute per-part quality metrics
    from src.confidence import (
        compute_extraction_coverage, compute_source_reliability,
        compute_classification_confidence, get_source_type,
        compute_lov_compliance, get_validation_action,
    )

    # If file extraction was used, prefer file source for metrics
    if file_attrs and file_result:
        effective_source_name = file_result.source_name
        effective_content = file_result.content
    else:
        effective_source_name = getattr(result, "source_name", "")
        effective_content = result.content

    mfg_pn_in_content = bool(
        effective_content and mfg_part_num
        and mfg_part_num.lower() in effective_content.lower()
    )

    file_method = getattr(file_result, "method", "") if file_result else ""
    effective_method = file_method if file_attrs and file_result else ""

    return {
        "part":            part,
        "part_class":      part_class,
        "tc_class_id":     get_tc_class_id(part_class),
        "in_json":         in_json,
        "attributes":      attributes,
        "lov_mismatches":  lov_mismatches,
        "range_originals": range_originals,
        "source_url":      source_url or "",
        # Quality metrics
        "extraction_coverage": compute_extraction_coverage(attributes, part_class),
        "source_reliability": compute_source_reliability(
            effective_source_name, mfg_pn_in_content,
            attributes, part_class, regex_agreement,
            method=effective_method,
        ),
        "classification_confidence": compute_classification_confidence(
            classify_source, validation_reason, in_json,
        ),
        "source_type": get_source_type(effective_source_name, method=effective_method),
        "lov_compliance": compute_lov_compliance(attributes, part_class, lov_mismatches),
        "validation_action": get_validation_action(validation_reason),
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
    if FRESH:
        if cache_path.exists():
            cache_path.unlink()
        progress_path = OUTPUT_DIR / "progress.json"
        if progress_path.exists():
            progress_path.unlink()
        print("  Fresh start: cache + progress cleared.")
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

    # Generate HTML executive summary (pre-processing)
    from src.report_generator import generate_run_summary
    from src.excel_handler import ExcelHandler
    metrics_dict = run_metrics.summary()
    generate_run_summary(
        results, metrics_dict, llm.token_usage,
        OUTPUT_DIR / "run_summary.html",
        input_file=EXCEL_PATH.name,
        model_name=llm.display_name(),
    )

    # ── Optional post-processing: deduplicate agent-extracted columns ─────
    if POST_PROCESS_DEDUP:
        from src.attr_schema import get_schema
        from src.post_processor import deduplicate_agent_columns

        # Build global TC attr set across all classes in this run
        tc_attr_set_global: set[str] = set()
        for r in results:
            cls = r.get("part_class", "")
            if cls:
                tc_attr_set_global.update(get_schema(cls))

        print(f"\n[PostProc] Deduplicating agent columns across {len(results)} parts...")
        post_results, merge_map = await deduplicate_agent_columns(
            results, tc_attr_set_global, llm
        )

        if merge_map:
            print(f"  Merged {len(merge_map)} agent column(s):")
            for removed, kept in sorted(merge_map.items()):
                print(f"    '{removed}' → '{kept}'")

            # Write post-processing Excel to output/post/ subfolder
            post_dir = OUTPUT_DIR / "post"
            post_handler = ExcelHandler(str(EXCEL_PATH), str(post_dir))
            post_written = post_handler.write_class_files(post_results)
            for path in post_written:
                print(f"  [post] -> {path}")

            generate_run_summary(
                post_results, metrics_dict, llm.token_usage,
                post_dir / "run_summary_post.html",
                input_file=EXCEL_PATH.name,
                model_name=llm.display_name(),
            )
            print(f"  [post] -> {post_dir / 'run_summary_post.html'}")
        else:
            print("  [PostProc] No duplicate agent columns found — post output skipped.")

    print(f"Done. {completed} parts processed.")


if __name__ == "__main__":
    # Windows requires ProactorEventLoop for subprocess support (CloakBrowser/Playwright)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
