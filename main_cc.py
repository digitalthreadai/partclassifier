"""
Part Classification Agent - Claude Code CLI edition
====================================================
Uses the `claude` CLI as the LLM and web search backend.
No API keys required - uses whatever LLM backend Claude Code is configured with.

Pipeline:
  1. Batch classification: classify all parts in batches of 100 (single CLI call each)
  2. Parallel search+extract: N workers fetch specs and extract attributes concurrently

Robustness features for large batches (20K+ parts):
  - Batch classification: ~100 parts per CLI call instead of 1 (75x faster)
  - Parallel workers: N concurrent search+extract (default 4)
  - Resume capability: saves progress to progress_cc.json after each part
  - Per-part error isolation: one failure doesn't kill the batch
  - Periodic Excel writes: output files updated every 50 parts
  - URL cache: reuses previously found URLs (url_cache.json)
  - Ctrl+C safe: saves progress and exits cleanly

Usage:
    python main_cc.py                    # 4 workers, resumes if progress exists
    python main_cc.py --workers 8        # 8 parallel workers
    python main_cc.py --fresh            # ignore previous progress
    python main_cc.py --workers 1        # sequential (for debugging)

Prerequisites:
    Claude Code CLI must be installed and configured.
    See: https://docs.anthropic.com/en/docs/claude-code
"""

import io
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Fix Windows console encoding — allow Unicode chars from scraped content
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import asyncio

from src.shared import rotate_manufacturers
from src.metrics import RunMetrics

# ── Thread-safe metrics wrapper ──────────────────────────────────────────────

class ThreadSafeMetrics:
    """Thread-safe wrapper around RunMetrics for use with ThreadPoolExecutor."""

    def __init__(self):
        self._metrics = RunMetrics()
        self._lock = threading.Lock()

    def record_part(self, classified: bool, attr_count: int):
        with self._lock:
            self._metrics.record_part(classified=classified, attr_count=attr_count)

    def record_llm_call(self, call_type: str):
        with self._lock:
            self._metrics.record_llm_call(call_type)

    def record_cache_hit(self, cache_type: str):
        with self._lock:
            self._metrics.record_cache_hit(cache_type)

    def record_regex(self, regex_count: int, agreement: dict | None = None):
        with self._lock:
            self._metrics.record_regex(regex_count, agreement)

    def print_summary(self):
        self._metrics.print_summary()

    def save_to_history(self, path):
        self._metrics.save_to_history(path)


# ── Sync retry for Claude CLI subprocess calls ───────────────────────────────

MAX_CLI_RETRIES = 3
CLI_RETRY_DELAY = 5

def _retry_cli(fn, label: str, safe_print_fn=print):
    """Retry a Claude CLI call on timeout/transient errors. Sync version."""
    for attempt in range(1, MAX_CLI_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            if attempt < MAX_CLI_RETRIES and ("timeout" in err_str or "rate" in err_str
                                               or "timed out" in err_str or "429" in str(e)):
                wait = CLI_RETRY_DELAY * attempt
                safe_print_fn(f"    {label} error (attempt {attempt}/{MAX_CLI_RETRIES}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                safe_print_fn(f"    {label} failed: {type(e).__name__}: {e}")
                return None
    return None

BASE_DIR      = Path(__file__).parent

def _get_output_dir() -> Path:
    """Get output directory from --output arg or default."""
    for i, arg in enumerate(sys.argv):
        if arg == "--output" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    return BASE_DIR / "output"

OUTPUT_DIR    = _get_output_dir()

def _get_progress_file() -> Path:
    """Get progress file path - use model-specific file if --model is specified."""
    for i, arg in enumerate(sys.argv):
        if arg == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1].lower().replace("-", "_")
            return BASE_DIR / f"progress_cc_{model}.json"
    return BASE_DIR / "progress_cc.json"

PROGRESS_FILE = _get_progress_file()

def _get_input_path() -> Path:
    """Get input Excel path from --input arg or default."""
    for i, arg in enumerate(sys.argv):
        if arg == "--input" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    return BASE_DIR / "input" / "PartClassifierInput.xlsx"

EXCEL_PATH = _get_input_path()

# Write Excel output every N completed parts (and at the end)
WRITE_INTERVAL = 50
DEFAULT_WORKERS = 4
CLASSIFY_BATCH_SIZE = 100

# Thread-safe printing
_print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print that prevents interleaved output."""
    with _print_lock:
        print(*args, **kwargs)



# _rotate_manufacturers is now imported from src.shared


# ── Progress persistence ─────────────────────────────────────────────────────

class ProgressTracker:
    """Thread-safe progress tracker with periodic disk saves."""

    def __init__(self, initial: dict | None = None):
        self._data: dict = initial or {}
        self._lock = threading.Lock()
        self._completed = 0
        self._errors = 0

    def is_done(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def save_result(self, key: str, result: dict, is_error: bool = False) -> int:
        """Save a result and return the new completed count."""
        with self._lock:
            self._data[key] = result
            if is_error:
                self._errors += 1
            self._completed += 1
            count = self._completed
        return count

    def save_to_disk(self) -> None:
        with self._lock:
            data_copy = dict(self._data)
        PROGRESS_FILE.write_text(
            json.dumps(data_copy, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def results(self) -> dict:
        with self._lock:
            return dict(self._data)

    @property
    def completed(self) -> int:
        with self._lock:
            return self._completed

    @property
    def errors(self) -> int:
        with self._lock:
            return self._errors

    @property
    def total_done(self) -> int:
        with self._lock:
            return len(self._data)


def load_progress() -> dict:
    """Load progress file. Returns {mfg_part_num: result_dict, ...}."""
    if PROGRESS_FILE.exists():
        try:
            data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {r["part"].get("Manufacturer Part Number", ""): r for r in data}
            return data
        except Exception as e:
            safe_print(f"  Warning: could not load progress file: {e}")
    return {}


# ── Phase 1: Batch classification ────────────────────────────────────────────

def batch_classify(client, pending: list[tuple[int, dict]]) -> dict[str, str]:
    """
    Classify all pending parts in batches of CLASSIFY_BATCH_SIZE.
    Returns {mfg_part_num: class_string, ...}.
    """
    if not pending:
        return {}

    classifications: dict[str, str] = {}
    total_parts = len(pending)
    num_batches = (total_parts + CLASSIFY_BATCH_SIZE - 1) // CLASSIFY_BATCH_SIZE

    safe_print(f"\n  Phase 1: Batch classification ({total_parts} parts in {num_batches} batch(es))...")

    for batch_idx in range(num_batches):
        start = batch_idx * CLASSIFY_BATCH_SIZE
        end = min(start + CLASSIFY_BATCH_SIZE, total_parts)
        batch = pending[start:end]

        batch_input = [
            {
                "key": str(part.get("Manufacturer Part Number") or "").strip(),
                "name": str(part.get("Part Name") or "").strip(),
            }
            for _, part in batch
        ]

        safe_print(f"    Batch {batch_idx + 1}/{num_batches}: classifying parts {start + 1}-{end}...")

        try:
            result = client.classify_batch(batch_input)
            classifications.update(result)
            safe_print(f"    Batch {batch_idx + 1}/{num_batches}: done ({len(result)} classified)")
        except Exception as e:
            safe_print(f"    Batch {batch_idx + 1}/{num_batches}: ERROR - {e}")
            # Fallback: mark all as Unclassified (they'll still get searched)
            for item in batch_input:
                classifications.setdefault(item["key"], "Unclassified")

    safe_print(f"  Phase 1 complete: {len(classifications)} parts classified")
    return classifications


# ── Phase 2: Per-part search + extract ────────────────────────────────────────

def _run_async(coro):
    """Run an async coroutine from synchronous/threaded code."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def process_part(
    part: dict, client, index: int, total: int, part_class: str,
    api_sources: list | None = None,
    metrics: ThreadSafeMetrics | None = None,
) -> dict:
    """Process a single part: scrape -> classify -> extract (single web scrape).

    Flow:
      1. Web scrape once via curl_cffi (WebScraper)
      2. Classify from scraped content (pattern matching, no LLM)
      3. Regex pre-extract attributes from scraped content (no LLM cost)
      4. Extract attributes via Claude CLI using the cached URL (no re-search)
      5. Fall back to Claude CLI web search only if curl_cffi found nothing
    """
    mfg_part_num    = str(part.get("Manufacturer Part Number") or "").strip()
    mfg_name        = str(part.get("Manufacturer Name")        or "").strip()
    part_name       = str(part.get("Part Name")                or "").strip()
    unit_of_measure = str(part.get("Unit of Measure")          or "inches").strip().lower()

    from src.class_extractor import extract_class_from_content
    from src.web_scraper import WebScraper

    # ── STEP 1: Web scrape once via curl_cffi ────────────────────────────────
    scraped_content = None
    scraped_url = None

    if part_class in ("Unclassified", "Unknown", ""):
        try:
            scraper = WebScraper()
            # Try cached URL first
            cached_url = scraper._cache.get(mfg_part_num)
            if cached_url:
                result = scraper._scrape_url(cached_url)
                if result and result.content and len(result.content) >= 200:
                    scraped_content = result.content
                    scraped_url = cached_url

            # If no cache hit, search DuckDuckGo
            if not scraped_content:
                urls = scraper._search_duckduckgo(f"{mfg_name} {mfg_part_num} specifications")
                for url in urls[:3]:
                    result = scraper._scrape_url(url)
                    if result and result.content and len(result.content) >= 200:
                        scraped_content = result.content
                        scraped_url = url
                        # Save to cache for later use by Claude CLI
                        scraper._cache[mfg_part_num] = url
                        from src.shared import save_cache
                        from src.web_scraper import _CACHE_PATH
                        save_cache(scraper._cache, _CACHE_PATH)
                        break

            scraper._session.close()
        except Exception as e:
            safe_print(f"  [{index}/{total}] Web scrape error: {e}")

    # ── STEP 2: Classify from scraped content (no LLM) ──────────────────────
    if part_class in ("Unclassified", "Unknown", ""):
        if scraped_content and len(scraped_content) >= 100:
            extracted_class = extract_class_from_content(
                scraped_content, scraped_url or "",
                mfg_name=mfg_name, mfg_part_num=mfg_part_num,
            )
            if extracted_class:
                part_class = extracted_class
                safe_print(f"  [{index}/{total}] Classified from web content: {part_class}")

    safe_print(
        f"\n{'-'*60}\n"
        f"  [{index}/{total}]\n"
        f"  Part #  : {mfg_part_num}\n"
        f"  Name    : {part_name}\n"
        f"  Maker   : {mfg_name}\n"
        f"  Unit    : {unit_of_measure}\n"
        f"  Class   : {part_class}"
    )

    # ── STEP 2.5: Regex pre-extraction from scraped content (no LLM cost) ───
    from src.regex_extractor import regex_extract, compute_agreement
    pre_extracted: dict[str, str] = {}
    if scraped_content:
        pre_extracted = regex_extract(scraped_content, part_class)
        if pre_extracted:
            safe_print(f"  [{index}/{total}] Regex: {len(pre_extracted)} attrs pre-extracted")
            if metrics:
                metrics.record_regex(len(pre_extracted))

    # ── STEP 3: Extract attributes ───────────────────────────────────────────
    from src.attr_schema import normalize_attrs
    attributes = {}
    source_url = ""

    # Try distributor APIs first (DigiKey, Mouser, McMaster) if configured
    for source in (api_sources or []):
        try:
            result = _run_async(source.search(mfg_name, mfg_part_num, unit_of_measure))
            if result and result.attributes and len(result.attributes) >= 3:
                attributes = normalize_attrs(result.attributes, part_class)
                source_url = result.source_url or ""
                safe_print(f"  [{index}/{total}] Source ({result.source_name}): {source_url}")
                break
        except Exception as e:
            safe_print(f"  [{index}/{total}] {source.name} error: {e}")

    # If we have a cached URL from scraping, use fetch_and_extract (no re-search)
    if not attributes and scraped_url:
        safe_print(f"  [{index}/{total}] Extracting from: {scraped_url}")
        result = _retry_cli(
            lambda: client._fetch_and_extract(
                scraped_url, mfg_part_num, part_class, part_name, unit_of_measure
            ),
            f"[{index}/{total}] Extract",
            safe_print,
        )
        if result:
            attributes, source_url = result
            if metrics:
                metrics.record_llm_call("extract")

    # Fall back to Claude CLI web search only if curl_cffi found nothing
    if not attributes:
        safe_print(f"  [{index}/{total}] Searching: {mfg_name} {mfg_part_num} ...")
        result = _retry_cli(
            lambda: client.search_and_extract(
                mfg_name, mfg_part_num, part_class, part_name, unit_of_measure
            ),
            f"[{index}/{total}] Search+Extract",
            safe_print,
        )
        if result:
            attributes, source_url = result
            if metrics:
                metrics.record_llm_call("extract")

    # Map classification to Classes.json hierarchy (strict Teamcenter alignment)
    from src.attr_schema import map_to_json_class
    original_class = part_class
    part_class, in_json = map_to_json_class(part_class)
    if part_class != original_class:
        safe_print(f"  [{index}/{total}] Mapped: {original_class} -> {part_class} (JSON)")

    # Re-classify from extracted attributes if still unclassified
    if part_class in ("Unclassified", "Unknown") and attributes:
        attr_text = " ".join(f"{k}: {v}" for k, v in attributes.items())
        extracted_class = extract_class_from_content(attr_text, source_url)
        if extracted_class:
            safe_print(f"  [{index}/{total}] Reclassified from attrs: {part_class} -> {extracted_class}")
            part_class = extracted_class
        else:
            attr_desc = ", ".join(f"{k}: {v}" for k, v in list(attributes.items())[:5])
            reclassify_text = f"{mfg_name} {mfg_part_num} - {attr_desc}"
            try:
                new_class = client.classify_single(reclassify_text)
                if new_class and new_class != "Unclassified":
                    safe_print(f"  [{index}/{total}] Reclassified (LLM): {part_class} -> {new_class}")
                    part_class = new_class
            except Exception as e:
                safe_print(f"  [{index}/{total}] Reclassify failed: {e}")

    # Fallback if nothing found at all
    if not attributes:
        safe_print(f"  [{index}/{total}] Web search returned nothing - falling back to part name")
        source_url = "part name"
        attributes = client.extract_from_part_name(
            part_name or f"{mfg_name} {mfg_part_num}", part_class, mfg_part_num, unit_of_measure
        )

    # Log regex/LLM agreement if both produced results
    if pre_extracted and attributes and metrics:
        agreement = compute_agreement(pre_extracted, attributes)
        metrics.record_regex(0, agreement)  # 0 = don't double-count

    # Secondary fallback: merge Part Name dimensions into extracted attrs (fill gaps only)
    if part_name and len(part_name) > 10:
        if not attributes or len(attributes) < 3:
            try:
                name_attrs = client.extract_from_part_name(
                    part_name, part_class, mfg_part_num, unit_of_measure
                )
                if name_attrs:
                    for k, v in name_attrs.items():
                        if k not in attributes:
                            attributes[k] = v
                    safe_print(f"  [{index}/{total}] Part name filled {len(name_attrs)} attrs")
            except Exception as e:
                safe_print(f"  [{index}/{total}] Part name extract error: {e}")

    if attributes:
        attr_lines = "\n".join(f"    {k}: {v}" for k, v in attributes.items())
        safe_print(f"  [{index}/{total}] Attrs ({len(attributes)}):\n{attr_lines}")
    else:
        safe_print(f"  [{index}/{total}] Attrs   : (none found)")
        # Evict cached URL that produced nothing - next run will try fresh search
        if scraped_url and mfg_part_num:
            from src.shared import load_cache, save_cache
            from src.web_scraper import _CACHE_PATH
            cache = load_cache(_CACHE_PATH)
            if mfg_part_num in cache:
                del cache[mfg_part_num]
                save_cache(cache, _CACHE_PATH)
                safe_print(f"  [{index}/{total}] Evicted bad cache: {scraped_url[:60]}")

    if metrics:
        metrics.record_part(
            classified=(part_class not in ("Unclassified", "Unknown", "Error", "")),
            attr_count=len(attributes),
        )

    from src.attr_schema import get_tc_class_id
    return {
        "part":         part,
        "part_class":   part_class,
        "tc_class_id":  get_tc_class_id(part_class),
        "in_json":      in_json,
        "attributes":   attributes,
        "source_url":   source_url or "",
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> tuple[bool, int, str]:
    """Parse CLI args. Returns (fresh_start, num_workers, model)."""
    fresh = "--fresh" in sys.argv
    workers = DEFAULT_WORKERS
    model = ""
    for i, arg in enumerate(sys.argv):
        if arg == "--workers" and i + 1 < len(sys.argv):
            try:
                workers = max(1, int(sys.argv[i + 1]))
            except ValueError:
                pass
        if arg == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]
    return fresh, workers, model


def main() -> None:
    fresh_start, num_workers, model = parse_args()

    if not EXCEL_PATH.exists():
        safe_print(f"ERROR: {EXCEL_PATH} not found")
        sys.exit(1)

    from src.claude_code_client import ClaudeCodeClient
    from src.excel_handler      import ExcelHandler
    from src.api_sources        import get_api_sources

    try:
        client = ClaudeCodeClient(model=model)
    except RuntimeError as e:
        safe_print(f"ERROR: {e}")
        sys.exit(1)

    api_sources = get_api_sources()

    handler = ExcelHandler(str(EXCEL_PATH), str(OUTPUT_DIR))
    parts   = rotate_manufacturers(handler.read_parts())
    total   = len(parts)

    # Load previous progress (unless --fresh)
    if fresh_start:
        prev_progress = {}
        safe_print(f"  Fresh start (ignoring previous progress)")
    else:
        prev_progress = load_progress()

    tracker = ProgressTracker(prev_progress)
    skipped = len(prev_progress)

    # Filter to only unprocessed parts
    pending: list[tuple[int, dict]] = []
    for i, part in enumerate(parts, start=1):
        key = str(part.get("Manufacturer Part Number") or "").strip()
        if not tracker.is_done(key):
            pending.append((i, part))

    safe_print(f"\nPart Classification Agent (Claude Code CLI)")
    safe_print(f"{'='*60}")
    safe_print(f"  Input    : {EXCEL_PATH.name}  ({total} parts)")
    safe_print(f"  Output   : {OUTPUT_DIR}/")
    safe_print(f"  Backend  : {client.display_name()}")
    safe_print(f"  Workers  : {num_workers}")
    safe_print(f"  URL cache: {client.cache_size} entries")
    if skipped > 0:
        safe_print(f"  Resuming : {skipped} parts already done, {len(pending)} remaining")
    if not pending:
        safe_print(f"\n  All parts already processed!")
        safe_print("Writing output files...")
        written = _write_output(handler, tracker)
        for path in written:
            safe_print(f"  -> {path}")
        safe_print("Done.")
        return

    start_time = time.time()
    run_metrics = ThreadSafeMetrics()

    # ── Phase 1: Batch classification (single-threaded, batches of 100) ──
    classifications = batch_classify(client, pending)

    classify_elapsed = time.time() - start_time
    safe_print(f"  Classification time: {classify_elapsed:.0f}s")

    # ── Phase 2: Parallel search + extract ──
    safe_print(f"\n  Phase 2: Search + extract ({len(pending)} parts, {num_workers} workers)...")

    SAVE_EVERY = 25  # Batch progress saves to reduce I/O
    last_write_count = 0
    last_save_count = 0
    shutdown_event = threading.Event()
    _save_lock = threading.Lock()

    def worker_task(index: int, part: dict) -> None:
        """Worker function for thread pool - search+extract only."""
        if shutdown_event.is_set():
            return

        key = str(part.get("Manufacturer Part Number") or "").strip()
        part_class = classifications.get(key, "Unclassified")

        try:
            result = process_part(part, client, index, total, part_class, api_sources, run_metrics)
            count = tracker.save_result(key, result)
        except Exception as e:
            safe_print(f"  [{index}/{total}] ERROR: {e}")
            error_result = {
                "part":         part,
                "part_class":   part_class,
                "tc_class_id":  "",
                "attributes":   {},
                "source_url":   f"error: {str(e)[:100]}",
            }
            count = tracker.save_result(key, error_result, is_error=True)

        # Batch progress saves (every SAVE_EVERY parts instead of every part)
        nonlocal last_write_count, last_save_count
        with _save_lock:
            if count - last_save_count >= SAVE_EVERY:
                last_save_count = count
                tracker.save_to_disk()

            # Periodic Excel writes
            if count - last_write_count >= WRITE_INTERVAL:
                last_write_count = count
                safe_print(f"\n  ... writing intermediate output ({tracker.total_done}/{total} parts) ...")
                _write_output(handler, tracker)

    # Run with thread pool
    try:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(worker_task, idx, part): idx
                for idx, part in pending
            }

            for future in as_completed(futures):
                if shutdown_event.is_set():
                    break
                future.result()

    except KeyboardInterrupt:
        safe_print(f"\n\nInterrupted by user.")
        safe_print(f"  Completed: {tracker.completed} parts this session")
        safe_print(f"  Total done: {tracker.total_done}/{total}")
        shutdown_event.set()
        tracker.save_to_disk()
        safe_print(f"  Progress saved - run again to resume.")
        _write_output(handler, tracker)
        sys.exit(0)

    # Final progress save
    tracker.save_to_disk()

    # Final summary
    elapsed = time.time() - start_time
    processed = tracker.completed
    errors = tracker.errors

    safe_print(f"\n{'='*60}")
    safe_print(f"  Processed : {processed} parts")
    if skipped > 0:
        safe_print(f"  Skipped   : {skipped} (from previous run)")
    if errors > 0:
        safe_print(f"  Errors    : {errors}")
    if processed > 0:
        safe_print(f"  Classify  : {classify_elapsed:.0f}s")
        safe_print(f"  Total time: {elapsed:.0f}s ({elapsed/processed:.1f}s per part)")
        safe_print(f"  Throughput: {processed / (elapsed / 3600):.0f} parts/hour")

    # Print metrics
    run_metrics.print_summary()
    run_metrics.save_to_history(BASE_DIR / "metrics_history.json")

    safe_print("Writing output files...")
    written = _write_output(handler, tracker)
    for path in written:
        safe_print(f"  -> {path}")

    # Clean up progress file on successful completion
    if tracker.total_done >= total and errors == 0:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
            safe_print(f"  Cleaned up {PROGRESS_FILE.name} (all parts complete)")

    safe_print("Done.")


def _write_output(handler, tracker: ProgressTracker) -> list[str]:
    """Write Excel output from the progress tracker."""
    results = list(tracker.results.values())
    return handler.write_class_files(results)


if __name__ == "__main__":
    main()
