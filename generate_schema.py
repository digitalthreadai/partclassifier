#!/usr/bin/env python3
"""
generate_schema.py - Auto-generate schema/aliases.json and schema/classification_hints.json.

Reads schema/Classes.json and schema/Attributes.json, then uses the configured
LLM (same .env as main.py) to generate:
  - aliases.json:              class_aliases + attribute_aliases
  - classification_hints.json: part-name keyword -> class hints for sanity checks

Usage:
    python generate_schema.py                  # generate both (default)
    python generate_schema.py --aliases        # generate aliases.json only
    python generate_schema.py --hints          # generate classification_hints.json only
    python generate_schema.py --merge          # fill gaps only, keep manual edits
    python generate_schema.py --dry-run        # preview without writing
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


_SCHEMA_DIR = Path(__file__).parent / "schema"
_CLASSES_JSON = _SCHEMA_DIR / "Classes.json"
_ATTRS_JSON = _SCHEMA_DIR / "Attributes.json"
_ALIASES_OUTPUT = _SCHEMA_DIR / "aliases.json"
_HINTS_OUTPUT = _SCHEMA_DIR / "classification_hints.json"

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
            print(f"  [WARN] {label} attempt {attempt}: JSON parse error - {e}")
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


def _llm_call_list(llm, prompt: str, label: str) -> Optional[list]:
    """Call LLM and parse JSON list response. Returns list or None."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            text = asyncio.run(llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.2,
            ))
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed = json.loads(text.strip())
            if isinstance(parsed, list):
                return parsed
            # If it's a dict with a "hints" key, unwrap it
            if isinstance(parsed, dict) and "hints" in parsed:
                return parsed["hints"]
            return None
        except json.JSONDecodeError as e:
            print(f"  [WARN] {label} attempt {attempt}: JSON parse error - {e}")
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
- CRITICAL: Do NOT use any of these class names as an alias for another class: {names_str}
  For example, do NOT list "Washer" as an alias for "Gasket" or "Screw" as an alias for "Bolt"
- Respond ONLY with valid JSON, no explanation

Format:
{{
  "Class Name": ["alias1", "alias2"],
  ...
}}"""


def _prompt_hints(class_names: list[str]) -> str:
    names_str = ", ".join(class_names)
    return f"""You are a mechanical engineering expert. Industrial part names in Excel input files use
abbreviations and shorthand to describe parts (e.g., "WSHR, SPT LK, M20" = Split Lock Washer).

For each class below, generate the keywords and abbreviations that commonly appear in part names
and descriptions. These will be used to sanity-check AI classification results.

Classes: {names_str}

Rules:
- Generate 2-6 UPPERCASE keywords per class (as they appear in part names)
- Include both full names and common abbreviations
- Order most-specific classes first (e.g., "Internal Tooth Lock Washer" before "Washer")
- Keywords should be things like: "INT TOOTH", "WSHR", "SPT LK", "HEX NUT", "CAP SCR", etc.
- Respond ONLY with valid JSON array, no explanation

Format:
[
  {{"keywords": ["INT TOOTH", "INTERNAL TOOTH"], "class": "Internal Tooth Lock Washer"}},
  {{"keywords": ["WASHER", "WSHR"], "class": "Washer"}},
  ...
]"""


# ── Generation functions ──────────────────────────────────────────────────────

def generate_aliases(llm, class_names: list[str], attr_names: list[str],
                     merge: bool, existing: dict) -> dict:
    """Generate aliases.json content."""
    result: dict = {
        "version": "1.0",
        "description": (
            "Auto-generated by generate_schema.py. "
            "Edit freely - re-run with --merge to preserve manual edits."
        ),
        "attribute_aliases": {},
        "class_aliases": {},
    }

    # ── 1. Attribute aliases ──────────────────────────────────────────────
    print("\n[STEP 1/2] Generating attribute aliases...")
    existing_attr_aliases = existing.get("attribute_aliases", {})
    attr_aliases: dict[str, list[str]] = {}

    for i, batch in enumerate(_batches(attr_names, _BATCH_SIZE), 1):
        if merge:
            batch = [n for n in batch if not existing_attr_aliases.get(n)]
            if not batch:
                continue

        label = f"attr-aliases batch {i}"
        print(f"  Batch {i}: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}")
        prompt = _prompt_attr_aliases(batch)
        data = _llm_call(llm, prompt, label)
        if data:
            for name in batch:
                match = next((v for k, v in data.items() if k.lower() == name.lower()), None)
                attr_aliases[name] = match if isinstance(match, list) else []
        else:
            for name in batch:
                attr_aliases[name] = []

    result["attribute_aliases"] = {**existing_attr_aliases, **attr_aliases}

    # ── 2. Class aliases ──────────────────────────────────────────────────
    print("\n[STEP 2/2] Generating class aliases...")
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

    return result


def generate_hints(llm, class_names: list[str], merge: bool, existing: list) -> list:
    """Generate classification_hints.json content."""
    print("\n[HINTS] Generating classification hints...")

    all_hints: list[dict] = []

    for i, batch in enumerate(_batches(class_names, _BATCH_SIZE), 1):
        label = f"hints batch {i}"
        print(f"  Batch {i}: {', '.join(batch[:3])}{'...' if len(batch) > 3 else ''}")
        prompt = _prompt_hints(batch)
        data = _llm_call_list(llm, prompt, label)
        if data:
            for entry in data:
                if isinstance(entry, dict) and "keywords" in entry and "class" in entry:
                    all_hints.append(entry)

    if merge and existing:
        # Merge: keep existing entries, add new classes
        existing_classes = {e["class"] for e in existing if isinstance(e, dict)}
        for hint in all_hints:
            if hint["class"] not in existing_classes:
                existing.append(hint)
        return existing

    return all_hints


# ── Main generation ───────────────────────────────────────────────────────────

def generate(mode: str = "both", merge: bool = False, dry_run: bool = False) -> None:
    from src.llm_client import LLMClient

    print("\n" + "=" * 60)
    print("  generate_schema.py - Schema Generator")
    print("=" * 60)

    try:
        llm = LLMClient()
        print(f"[LLM] Provider: {os.getenv('LLM_PROVIDER', 'unknown')} | Model: {llm.model}")
    except (ValueError, ImportError) as e:
        print(f"[ERROR] LLM init failed: {e}")
        print("  Check your .env file - same config as main.py")
        sys.exit(1)

    class_names = _load_all_classes()
    attrs = _load_all_attrs()
    attr_names = [a.get("name", "") for a in attrs if a.get("name")]

    print(f"[INFO] {len(class_names)} classes, {len(attr_names)} attributes")

    # ── Generate aliases ──────────────────────────────────────────────────
    if mode in ("both", "aliases"):
        existing_aliases: dict = {}
        if merge and _ALIASES_OUTPUT.exists():
            with open(_ALIASES_OUTPUT, "r", encoding="utf-8") as f:
                existing_aliases = json.load(f)
            print(f"[MERGE] Loaded existing {_ALIASES_OUTPUT.name}")

        aliases_result = generate_aliases(llm, class_names, attr_names, merge, existing_aliases)

        n_attrs = len(aliases_result.get("attribute_aliases", {}))
        n_classes = len(aliases_result.get("class_aliases", {}))
        print(f"\n[DONE] aliases.json: {n_attrs} attr aliases, {n_classes} class aliases")

        if dry_run:
            print(f"[DRY-RUN] Would write to: {_ALIASES_OUTPUT}")
        else:
            _SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
            with open(_ALIASES_OUTPUT, "w", encoding="utf-8") as f:
                json.dump(aliases_result, f, indent=2, ensure_ascii=False)
            print(f"[WRITE] {_ALIASES_OUTPUT} ({_ALIASES_OUTPUT.stat().st_size} bytes)")

    # ── Generate hints ────────────────────────────────────────────────────
    if mode in ("both", "hints"):
        existing_hints: list = []
        if merge and _HINTS_OUTPUT.exists():
            with open(_HINTS_OUTPUT, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_hints = data.get("hints", []) if isinstance(data, dict) else data
            print(f"[MERGE] Loaded existing {_HINTS_OUTPUT.name}")

        hints_result = generate_hints(llm, class_names, merge, existing_hints)

        print(f"\n[DONE] classification_hints.json: {len(hints_result)} class hints")

        hints_doc = {
            "version": "1.0",
            "description": (
                "Auto-generated by generate_schema.py. "
                "Part-name keyword -> class hints for classification sanity checks."
            ),
            "hints": hints_result,
        }

        if dry_run:
            print(f"[DRY-RUN] Would write to: {_HINTS_OUTPUT}")
        else:
            _SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
            with open(_HINTS_OUTPUT, "w", encoding="utf-8") as f:
                json.dump(hints_doc, f, indent=2, ensure_ascii=False)
            print(f"[WRITE] {_HINTS_OUTPUT} ({_HINTS_OUTPUT.stat().st_size} bytes)")

    print("\nNext step: python main.py  (or main_cc.py)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-generate schema/aliases.json and schema/classification_hints.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python generate_schema.py                  # generate both (default)
  python generate_schema.py --aliases        # aliases.json only
  python generate_schema.py --hints          # classification_hints.json only
  python generate_schema.py --merge          # fill gaps, keep manual edits
  python generate_schema.py --dry-run        # preview without writing
""",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--aliases", action="store_true", help="Generate aliases.json only")
    group.add_argument("--hints", action="store_true", help="Generate classification_hints.json only")
    group.add_argument("--both", action="store_true", help="Generate both (default)")
    parser.add_argument("--merge", action="store_true", help="Fill gaps only, keep manual edits")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if args.aliases:
        mode = "aliases"
    elif args.hints:
        mode = "hints"
    else:
        mode = "both"

    generate(mode=mode, merge=args.merge, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
