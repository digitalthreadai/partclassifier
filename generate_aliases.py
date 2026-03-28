#!/usr/bin/env python3
"""
generate_aliases.py - Auto-generate input/aliases.json using LLM knowledge.

Reads input/Classes.json and input/Attributes.json, then uses the configured
LLM (same .env as main.py) to generate:
  - attribute_aliases:         common synonyms/abbreviations per attribute
  - class_aliases:             alternate names per class
  - class_attribute_overrides: context-aware attr mapping per class
                                (e.g., "size" means Thread Size for Bolt, OD for Washer)

Usage:
    python generate_aliases.py                  # generate fresh aliases.json
    python generate_aliases.py --merge          # fill gaps only, keep manual edits
    python generate_aliases.py --dry-run        # preview without writing
    python generate_aliases.py --output path/to/aliases.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


_INPUT_DIR = Path(__file__).parent / "input"
_CLASSES_JSON = _INPUT_DIR / "Classes.json"
_ATTRS_JSON = _INPUT_DIR / "Attributes.json"
_DEFAULT_OUTPUT = _INPUT_DIR / "aliases.json"

_BATCH_SIZE = 12       # attributes/classes per LLM call
_RETRY_DELAY = 3       # seconds between retries on rate limit
_MAX_RETRIES = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flatten_tree(nodes: list[dict], result: list[str]) -> None:
    """Recursively collect all class names from the tree."""
    for node in nodes:
        name = node.get("name", "").strip()
        if name:
            result.append(name)
        _flatten_tree(node.get("children", []), result)


def _load_all_classes() -> list[str]:
    if not _CLASSES_JSON.exists():
        print(f"[ERROR] {_CLASSES_JSON} not found")
        sys.exit(1)
    with open(_CLASSES_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    names: list[str] = []
    _flatten_tree(data.get("tree", data.get("classes", [])), names)
    return names


def _load_all_attrs() -> list[dict]:
    if not _ATTRS_JSON.exists():
        print(f"[ERROR] {_ATTRS_JSON} not found")
        sys.exit(1)
    with open(_ATTRS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("attributes", data.get("tree", []))


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _llm_call(llm, prompt: str, label: str) -> Optional[dict]:
    """Call LLM and parse JSON response. Returns dict or None on failure."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            text = asyncio.run(llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
                temperature=0.2,
            ))
            # Extract JSON block
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            print(f"  [WARN] {label} attempt {attempt}: JSON parse error — {e}")
        except Exception as e:
            err = str(e)
            if "rate" in err.lower() or "429" in err:
                print(f"  [WARN] {label} attempt {attempt}: rate limit, retrying in {_RETRY_DELAY}s...")
                time.sleep(_RETRY_DELAY)
            else:
                print(f"  [WARN] {label} attempt {attempt}: {e}")
        if attempt < _MAX_RETRIES:
            time.sleep(1)
    return None


# ── LLM prompts ───────────────────────────────────────────────────────────────

def _prompt_attr_aliases(attr_names: list[str]) -> str:
    names_str = ", ".join(attr_names)
    return f"""You are a mechanical engineering expert with deep knowledge of Teamcenter PDM and part classification.

For each attribute name below, list the common synonyms, abbreviations, and alternate terms that
an extraction AI might use when reading a technical datasheet or distributor page.
Include: engineering shorthand (ID, OD, THK), full alternate names, and common LLM-generated variants.

Attributes: {names_str}

Rules:
- Include 4-8 aliases per attribute
- Focus on what appears on datasheets and distributor sites
- Do NOT include the canonical name itself in the alias list
- Respond ONLY with valid JSON, no explanation

Format:
{{
  "Attribute Name": ["alias1", "alias2", "alias3"],
  ...
}}"""


def _prompt_class_aliases(class_names: list[str]) -> str:
    names_str = ", ".join(class_names)
    return f"""You are a mechanical engineering expert with deep knowledge of Teamcenter PDM classification.

For each mechanical part class name below, list alternate names, abbreviations, and common synonyms
that an AI classifier might use to describe the same part type.

Classes: {names_str}

Rules:
- Include 2-5 aliases per class
- Focus on what appears on datasheets, distributor sites, and engineering catalogs
- Do NOT include the canonical name itself in the alias list
- Respond ONLY with valid JSON, no explanation

Format:
{{
  "Class Name": ["alias1", "alias2"],
  ...
}}"""


def _prompt_class_overrides(class_names: list[str], attr_names: list[str]) -> str:
    names_str = ", ".join(class_names)
    attrs_str = ", ".join(attr_names)
    return f"""You are a mechanical engineering expert with deep knowledge of Teamcenter PDM classification.

For each part class below, identify ambiguous attribute words that an extraction AI might use,
and map them to the correct canonical attribute name from the given attribute list.

Focus on words like: size, dia, diameter, bore, od, id, thk, length, gauge, rating
that mean different things depending on the part class.

Part classes: {names_str}

Available canonical attributes: {attrs_str}

Rules:
- Only include entries where the mapping is truly class-specific (not universal)
- Skip a class if there are no context-specific ambiguous mappings
- Respond ONLY with valid JSON, no explanation

Format:
{{
  "Class Name": {{
    "ambiguous_word": "Canonical Attribute Name",
    "size": "Thread Size"
  }},
  ...
}}"""


# ── Main generation ───────────────────────────────────────────────────────────

def generate(
    merge: bool = False,
    dry_run: bool = False,
    output_path: Path = _DEFAULT_OUTPUT,
) -> dict:
    from src.llm_client import LLMClient

    print("\n" + "=" * 60)
    print("  generate_aliases.py — LLM Alias Generator")
    print("=" * 60)

    try:
        llm = LLMClient()
        print(f"[LLM] Provider: {os.getenv('LLM_PROVIDER', 'unknown')} | Model: {llm.model}")
    except (ValueError, ImportError) as e:
        print(f"[ERROR] LLM init failed: {e}")
        print("  Check your .env file — same config as main.py")
        sys.exit(1)

    # Load existing aliases.json if merging
    existing: dict = {}
    if merge and output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        print(f"[MERGE] Loaded existing {output_path.name} — will only fill gaps")

    class_names = _load_all_classes()
    attrs = _load_all_attrs()
    attr_names = [a.get("name", "") for a in attrs if a.get("name")]

    print(f"[INFO] {len(class_names)} classes, {len(attr_names)} attributes to process")

    result: dict = {
        "version": "1.0",
        "description": (
            "Auto-generated by generate_aliases.py. "
            "Edit freely — re-run with --merge to preserve manual edits."
        ),
        "attribute_aliases": {},
        "class_aliases": {},
        "class_attribute_overrides": {},
    }

    # ── 1. Attribute aliases ──────────────────────────────────────────────────
    print("\n[STEP 1/3] Generating attribute aliases...")
    existing_attr_aliases = existing.get("attribute_aliases", {})
    attr_aliases: dict[str, list[str]] = {}

    for i, batch in enumerate(_batches(attr_names, _BATCH_SIZE), 1):
        if merge:
            # Only process attrs with missing/empty aliases
            batch = [n for n in batch if not existing_attr_aliases.get(n)]
            if not batch:
                continue

        label = f"attr-aliases batch {i}"
        print(f"  Batch {i}: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}")
        prompt = _prompt_attr_aliases(batch)
        data = _llm_call(llm, prompt, label)
        if data:
            for name in batch:
                # Match case-insensitively
                match = next((v for k, v in data.items() if k.lower() == name.lower()), None)
                attr_aliases[name] = match if isinstance(match, list) else []
        else:
            print(f"  [WARN] Batch {i} failed — leaving empty for manual fill")
            for name in batch:
                attr_aliases[name] = []

    # Merge with existing
    result["attribute_aliases"] = {**existing_attr_aliases, **attr_aliases}

    # ── 2. Class aliases ─────────────────────────────────────────────────────
    print("\n[STEP 2/3] Generating class aliases...")
    existing_class_aliases = existing.get("class_aliases", {})
    class_aliases: dict[str, list[str]] = {}

    for i, batch in enumerate(_batches(class_names, _BATCH_SIZE), 1):
        if merge:
            batch = [n for n in batch if not existing_class_aliases.get(n)]
            if not batch:
                continue

        label = f"class-aliases batch {i}"
        print(f"  Batch {i}: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}")
        prompt = _prompt_class_aliases(batch)
        data = _llm_call(llm, prompt, label)
        if data:
            for name in batch:
                match = next((v for k, v in data.items() if k.lower() == name.lower()), None)
                class_aliases[name] = match if isinstance(match, list) else []
        else:
            for name in batch:
                class_aliases[name] = []

    result["class_aliases"] = {**existing_class_aliases, **class_aliases}

    # ── 3. Class attribute overrides ─────────────────────────────────────────
    print("\n[STEP 3/3] Generating class attribute overrides...")
    existing_overrides = existing.get("class_attribute_overrides", {})
    class_overrides: dict[str, dict[str, str]] = {}

    for i, batch in enumerate(_batches(class_names, _BATCH_SIZE), 1):
        if merge:
            batch = [n for n in batch if n not in existing_overrides]
            if not batch:
                continue

        label = f"class-overrides batch {i}"
        print(f"  Batch {i}: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}")
        prompt = _prompt_class_overrides(batch, attr_names[:30])  # limit attr list to avoid token overflow
        data = _llm_call(llm, prompt, label)
        if data:
            for name in batch:
                match = next((v for k, v in data.items() if k.lower() == name.lower()), None)
                if isinstance(match, dict) and match:
                    class_overrides[name] = match

    result["class_attribute_overrides"] = {**existing_overrides, **class_overrides}

    # ── Summary ───────────────────────────────────────────────────────────────
    n_attrs = len(result["attribute_aliases"])
    n_classes = len(result["class_aliases"])
    n_overrides = len(result["class_attribute_overrides"])
    print(f"\n[DONE] {n_attrs} attr aliases, {n_classes} class aliases, {n_overrides} class overrides")

    if dry_run:
        print("\n[DRY-RUN] Preview (first 500 chars):")
        print(json.dumps(result, indent=2)[:500] + "\n...")
        print(f"[DRY-RUN] Would write to: {output_path}")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"[WRITE] {output_path} ({output_path.stat().st_size} bytes)")
        print("\nNext step: python main.py  (or main_cc.py)")

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-generate input/aliases.json using LLM knowledge.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python generate_aliases.py
  python generate_aliases.py --merge
  python generate_aliases.py --dry-run
  python generate_aliases.py --output input/aliases.json
""",
    )
    parser.add_argument(
        "--merge", action="store_true",
        help="Fill gaps only — preserve existing manual edits in aliases.json"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview output without writing to disk"
    )
    parser.add_argument(
        "--output", type=str, default=str(_DEFAULT_OUTPUT),
        help=f"Output path (default: {_DEFAULT_OUTPUT})"
    )
    args = parser.parse_args()
    generate(merge=args.merge, dry_run=args.dry_run, output_path=Path(args.output))


if __name__ == "__main__":
    main()
