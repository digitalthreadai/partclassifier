"""
Benchmark runner: Run the PartClassifier pipeline and save structured results
to a JSON file for cross-model comparison.

Usage:
    python benchmark.py --label groq          # uses .env config (Groq)
    python benchmark.py --label opus          # change .env to anthropic/opus first
    python benchmark.py --label sonnet        # change .env to anthropic/sonnet first

Results are saved to benchmark_results/<label>.json
"""

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Force unbuffered output so progress shows in real-time
os.environ["PYTHONUNBUFFERED"] = "1"

from dotenv import load_dotenv
load_dotenv()

BASE_DIR   = Path(__file__).parent
EXCEL_PATH = BASE_DIR / "input" / "PartClassifierInput_1000.xlsx"
OUTPUT_DIR = BASE_DIR / "output"
RESULTS_DIR = BASE_DIR / "benchmark_results"


async def main(label: str) -> None:
    if not EXCEL_PATH.exists():
        print(f"ERROR: {EXCEL_PATH} not found")
        sys.exit(1)

    RESULTS_DIR.mkdir(exist_ok=True)

    from src.llm_client         import LLMClient
    from src.excel_handler      import ExcelHandler
    from src.part_classifier    import PartClassifier
    from src.web_scraper        import WebScraper
    from src.attribute_extractor import AttributeExtractor
    from collections import defaultdict

    try:
        llm = LLMClient()
    except (ValueError, ImportError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    handler        = ExcelHandler(str(EXCEL_PATH), str(OUTPUT_DIR))
    classifier     = PartClassifier(llm)
    attr_extractor = AttributeExtractor(llm)

    # Rotate manufacturers
    def _rotate_manufacturers(parts):
        buckets = defaultdict(list)
        for p in parts:
            mfg = str(p.get("Manufacturer Name") or "").strip().upper()
            buckets[mfg].append(p)
        sorted_buckets = sorted(buckets.values(), key=len, reverse=True)
        rotated = []
        while any(sorted_buckets):
            for bucket in sorted_buckets:
                if bucket:
                    rotated.append(bucket.pop(0))
            sorted_buckets = [b for b in sorted_buckets if b]
        return rotated

    parts = _rotate_manufacturers(handler.read_parts())
    total = len(parts)

    print(f"\nBenchmark Run: {label}")
    print(f"{'='*60}")
    print(f"  Input  : {EXCEL_PATH.name}  ({total} parts)")
    print(f"  Model  : {llm.display_name()}")
    print(f"  Output : {RESULTS_DIR / f'{label}.json'}")

    results = []
    errors = 0
    start_time = time.time()

    async with WebScraper() as scraper:
        for i, part in enumerate(parts, 1):
            mfg_part_num    = str(part.get("Manufacturer Part Number") or "").strip()
            mfg_name        = str(part.get("Manufacturer Name") or "").strip()
            part_name       = str(part.get("Part Name") or "").strip()
            unit_of_measure = str(part.get("Unit of Measure") or "inches").strip().lower()

            print(f"\n[{i}/{total}] {mfg_name} / {mfg_part_num}", flush=True)

            part_result = {
                "index": i,
                "mfg_part_num": mfg_part_num,
                "mfg_name": mfg_name,
                "part_name": part_name,
                "unit": unit_of_measure,
                "classification": None,
                "source_url": None,
                "source_name": None,
                "attributes": {},
                "attr_count": 0,
                "error": None,
                "elapsed_s": 0,
            }

            part_start = time.time()
            try:
                # 1. Classify
                part_class = await classifier.classify(part_name if part_name else mfg_part_num)
                part_result["classification"] = part_class
                print(f"  Class: {part_class}", flush=True)

                # 2. Scrape
                result = await scraper.find_and_scrape(mfg_name, mfg_part_num, unit_of_measure)

                # 3. Extract
                if result.attributes and len(result.attributes) >= 3:
                    from src.attr_schema import normalize_attrs
                    attributes = normalize_attrs(result.attributes, part_class)
                    source_url = result.source_url
                    source_name = result.source_name
                elif result.content:
                    attributes = await attr_extractor.extract(
                        result.content, part_class, mfg_part_num, part_name, unit_of_measure
                    )
                    source_url = result.source_url
                    source_name = "web"
                else:
                    if part_name:
                        attributes = await attr_extractor.extract_from_part_name(
                            part_name, part_class, mfg_part_num, unit_of_measure
                        )
                        source_url = "part name"
                        source_name = "part_name"
                    else:
                        attributes = {}
                        source_url = None
                        source_name = "none"

                part_result["attributes"] = attributes
                part_result["attr_count"] = len(attributes)
                part_result["source_url"] = source_url
                part_result["source_name"] = source_name
                print(f"  Source: {source_name} | Attrs: {len(attributes)}", flush=True)

            except Exception as e:
                part_result["error"] = str(e)
                errors += 1
                print(f"  ERROR: {e}")

            part_result["elapsed_s"] = round(time.time() - part_start, 1)
            results.append(part_result)

            # Save progress every 10 parts
            if i % 10 == 0:
                _save_results(label, llm.display_name(), results, start_time, total, errors)
                print(f"  [Progress saved: {i}/{total}]")

    total_elapsed = round(time.time() - start_time, 1)
    _save_results(label, llm.display_name(), results, start_time, total, errors, final=True)

    # Also write output Excel files
    excel_results = []
    for r in results:
        excel_results.append({
            "part": {
                "Part Number": f"TEST-{r['index']:04d}",
                "Part Name": r["part_name"],
                "Manufacturer Part Number": r["mfg_part_num"],
                "Manufacturer Name": r["mfg_name"],
                "Unit of Measure": r["unit"],
            },
            "part_class": r["classification"] or "Unknown",
            "attributes": r["attributes"],
            "source_url": r["source_url"] or "",
        })
    written = handler.write_class_files(excel_results)

    print(f"\n{'='*60}")
    print(f"  Total parts  : {total}")
    print(f"  Errors       : {errors}")
    print(f"  Total time   : {total_elapsed}s ({total_elapsed/60:.1f} min)")
    print(f"  Avg per part : {total_elapsed/total:.1f}s")
    print(f"  Results      : {RESULTS_DIR / f'{label}.json'}")
    for p in written:
        print(f"  -> {p}")
    print("Done.")


def _save_results(label, model_name, results, start_time, total, errors, final=False):
    elapsed = round(time.time() - start_time, 1)
    data = {
        "label": label,
        "model": model_name,
        "total_parts": total,
        "processed": len(results),
        "errors": errors,
        "elapsed_s": elapsed,
        "final": final,
        "parts": results,
    }
    out_path = RESULTS_DIR / f"{label}.json"
    out_path.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark PartClassifier")
    parser.add_argument("--label", required=True, help="Label for this run (e.g., groq, opus, sonnet)")
    args = parser.parse_args()
    asyncio.run(main(args.label))
