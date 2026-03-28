"""
Claude Code CLI client — uses the `claude` CLI as the LLM and web search backend.

No API keys required. The `claude` CLI uses whatever LLM backend the user has
configured (Azure, Anthropic, etc.).

Features:
  - URL cache: reuses previously found URLs to skip web search on re-runs
  - Source URL tracking: extracts and returns the actual URL fetched
  - Trusted domain enforcement: prioritizes known-good distributor sites
  - Cache-hit fast path: fetches a known URL directly without searching

Usage:
    client = ClaudeCodeClient()
    part_class = client.classify("Split Lock Washer 5/16")
    attrs, source = client.search_and_extract("McMaster", "92147A200", "Split Lock Washer", ...)
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from src.attr_schema import KNOWN_CLASSES, get_schema, normalize_attrs
from src.attribute_extractor import _unit_instructions, _parse_json, _example_json

# Domains known to have reliable industrial fastener spec data
PREFERRED_DOMAINS = [
    "skdin.com",
    "olander.com",
    "aftfasteners.com",
    "aspenfasteners.com",
    "boltdepot.com",
    "albanycountyfasteners.com",
    "fastenal.com",
    "zoro.com",
    "lily-bearing.com",
]

# URL cache file path
_CACHE_PATH = Path(__file__).parent.parent / "url_cache.json"


def _load_cache() -> dict:
    from src.shared import load_cache
    return load_cache(_CACHE_PATH)


def _save_cache(cache: dict) -> None:
    from src.shared import save_cache
    save_cache(cache, _CACHE_PATH)


class ClaudeCodeClient:
    """Wraps the `claude` CLI for LLM and web search operations."""

    def __init__(self, claude_cmd: str = "claude", model: str = ""):
        # On Windows, npm CLIs are .cmd files; shutil.which() resolves them properly
        resolved = shutil.which(claude_cmd)
        if not resolved:
            raise RuntimeError(
                f"'{claude_cmd}' not found on PATH.\n"
                "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
            )
        self.claude_cmd = resolved
        self._model = model  # e.g. "opus", "sonnet", or full model ID
        self._cache = _load_cache()
        self._cache_lock = threading.Lock()
        self._verify_cli()

    def _verify_cli(self) -> None:
        """Check that the claude CLI is available."""
        try:
            result = subprocess.run(
                [self.claude_cmd, "--version"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"claude CLI returned exit code {result.returncode}.\n"
                    f"stderr: {result.stderr.strip()}"
                )
            version = result.stdout.strip()
            print(f"  Claude CLI: {version}")
        except FileNotFoundError:
            raise RuntimeError(
                "claude CLI not found on PATH.\n"
                "Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
            )

    # ── Core subprocess runner ────────────────────────────────────────────────

    def _run_claude(
        self,
        prompt: str,
        allowed_tools: list[str] | None = None,
        timeout: int = 120,
    ) -> str:
        """Run the claude CLI with a prompt and return stdout text."""
        cmd = [self.claude_cmd, "-p", "--output-format", "text"]

        if self._model:
            cmd += ["--model", self._model]

        if allowed_tools:
            cmd += ["--allowedTools", ",".join(allowed_tools)]

        # Strip CLAUDECODE env var to allow running from within a Claude Code session
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if stderr:
                    print(f"    claude CLI error: {stderr[:200]}", file=sys.stderr)
                return ""
            return result.stdout.strip()

        except subprocess.TimeoutExpired:
            print(f"    claude CLI timed out after {timeout}s", file=sys.stderr)
            return ""
        except Exception as e:
            print(f"    claude CLI error: {e}", file=sys.stderr)
            return ""

    # ── Public API ────────────────────────────────────────────────────────────

    def classify(self, part_name: str) -> str:
        """Classify a single part name. Returns 1-4 word class string."""
        prompt = (
            "You are a mechanical parts classification expert. "
            "Reply with ONLY the category name, 1-4 words, no explanation.\n\n"
            f"Classify this mechanical part into a standard category.\n"
            f"Part name: {part_name}\n\n"
            f"Common categories: {', '.join(KNOWN_CLASSES)}"
        )

        result = self._run_claude(prompt, timeout=120)
        if not result:
            return "Unclassified"

        # Clean up: remove quotes, periods, extra whitespace
        cleaned = result.strip().strip('"').strip("'").strip(".").strip()
        return cleaned or "Unclassified"

    def classify_batch(self, parts: list[dict]) -> dict[str, str]:
        """
        Classify multiple parts in a single CLI call.
        Takes list of {"key": mfg_part_num, "name": part_name} dicts.
        Returns {mfg_part_num: class_string, ...}.
        Much faster than calling classify() per part (~15s for 100 parts vs 15s each).
        """
        if not parts:
            return {}

        # Build numbered list for the prompt
        lines = []
        for i, p in enumerate(parts, start=1):
            lines.append(f'{i}. "{p["name"]}"')
        parts_list = "\n".join(lines)

        prompt = (
            "You are a mechanical parts classification expert.\n\n"
            f"Classify each part below into a standard category (1-4 words).\n\n"
            f"Common categories: {', '.join(KNOWN_CLASSES)}\n\n"
            f"Parts to classify:\n{parts_list}\n\n"
            "RESPOND WITH ONLY a JSON object mapping the part number (1, 2, 3...) "
            "to its category. No explanation.\n"
            f'Example: {{"1": "Flat Washer", "2": "Hex Bolt", "3": "Split Lock Washer"}}'
        )

        # Longer timeout for large batches
        timeout = max(120, len(parts) * 2)
        raw = self._run_claude(prompt, timeout=timeout)

        if not raw:
            return {p["key"]: "Unclassified" for p in parts}

        parsed = _parse_json(raw)
        if not parsed:
            return {p["key"]: "Unclassified" for p in parts}

        # Map numbered results back to part keys
        result = {}
        for i, p in enumerate(parts, start=1):
            cls = str(parsed.get(str(i), parsed.get(i, "Unclassified"))).strip()
            cls = cls.strip('"').strip("'").strip(".").strip()
            result[p["key"]] = cls or "Unclassified"

        return result

    def classify_single(self, text: str) -> str:
        """Classify a single part from text (web content, attributes, or part name)."""
        text = text[:600].strip()
        prompt = (
            "You are an industrial parts classification expert.\n"
            "Classify this part into the MOST SPECIFIC category (1-4 words).\n"
            "Reply with ONLY the category name. No explanation.\n\n"
            f"INPUT:\n{text}\n\n"
            f"Available categories: {', '.join(KNOWN_CLASSES)}\n\n"
            "If unsure, pick the closest match. Only use 'Unclassified' as last resort."
        )
        raw = self._run_claude(prompt, timeout=60)
        if raw:
            return raw.strip().strip('"').strip("'").strip(".")
        return "Unclassified"

    def search_and_extract(
        self,
        mfg_name: str,
        mfg_part_num: str,
        part_class: str,
        part_name: str,
        unit_of_measure: str,
    ) -> tuple[dict[str, str], str]:
        """
        Search the web for part specs and extract attributes.
        Uses URL cache for previously found parts. Thread-safe.
        Returns (attributes_dict, source_url).
        Returns ({}, "") if nothing found.
        """
        # ── Cache hit: fetch known URL directly ──
        with self._cache_lock:
            cached_url = self._cache.get(mfg_part_num)

        if cached_url:
            print(f"    Cache hit: {cached_url}")
            attrs, url = self._fetch_and_extract(
                cached_url, mfg_part_num, part_class, part_name, unit_of_measure
            )
            if attrs:
                return attrs, url
            # Cache miss (URL dead) — remove and fall through to search
            print(f"    Cached URL failed, re-searching...")
            with self._cache_lock:
                self._cache.pop(mfg_part_num, None)
                _save_cache(self._cache)

        # ── Phase 1: Search trusted domains first ──
        attrs, url = self._search_trusted_domains(
            mfg_name, mfg_part_num, part_class, part_name, unit_of_measure
        )
        if attrs:
            self._update_cache(mfg_part_num, url)
            return attrs, url

        # ── Phase 2: General web search ──
        attrs, url = self._search_general(
            mfg_name, mfg_part_num, part_class, part_name, unit_of_measure
        )
        if attrs:
            self._update_cache(mfg_part_num, url)
            return attrs, url

        return {}, ""

    def _update_cache(self, mfg_part_num: str, url: str) -> None:
        """Thread-safe cache update."""
        with self._cache_lock:
            self._cache[mfg_part_num] = url
            _save_cache(self._cache)

    def extract_from_part_name(
        self,
        part_name: str,
        part_class: str,
        mfg_part_num: str,
        unit_of_measure: str,
    ) -> dict[str, str]:
        """Fallback: extract any dimensions encoded in the part name itself."""
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)

        prompt = (
            "You are a mechanical parts expert. "
            "Return ONLY valid JSON. No markdown, no explanation.\n\n"
            f"Extract any dimensions or specifications encoded in this part name.\n\n"
            f"Part Number  : {mfg_part_num}\n"
            f"Part Class   : {part_class}\n"
            f"Part Name    : {part_name}\n"
            f"Target Unit  : {unit_label}\n"
            f"UNIT RULE    : {convert_note}\n\n"
            f"Return a JSON object with attribute names as keys and values in {unit_short}. "
            f"Return {{}} if nothing can be extracted."
        )

        raw = self._run_claude(prompt, timeout=120)
        if not raw:
            return {}

        result = _parse_json(raw)
        return normalize_attrs(result, part_class)

    def display_name(self) -> str:
        """Human-readable string for console output."""
        return "Claude Code CLI"

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    # ── Internal search strategies ────────────────────────────────────────────

    def _search_trusted_domains(
        self,
        mfg_name: str,
        mfg_part_num: str,
        part_class: str,
        part_name: str,
        unit_of_measure: str,
    ) -> tuple[dict[str, str], str]:
        """Phase 1: Search specifically within trusted distributor domains."""
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)
        schema_attrs = get_schema(part_class)
        example = _example_json(unit_short)
        domains_list = " OR ".join(f"site:{d}" for d in PREFERRED_DOMAINS)

        prompt = (
            "You are a mechanical parts data extraction specialist.\n\n"
            "TASK: Find specifications for this part from TRUSTED distributor websites.\n\n"
            f"Part Details:\n"
            f"  Manufacturer : {mfg_name}\n"
            f"  Part Number  : {mfg_part_num}\n"
            f"  Part Name    : {part_name}\n"
            f"  Part Class   : {part_class}\n"
            f"  Target Unit  : {unit_label}\n\n"
            "SEARCH STRATEGY (follow this EXACTLY):\n"
            f'1. Search for: {mfg_part_num} ({domains_list})\n'
            f'2. If no results, search for: {mfg_name} {mfg_part_num} specifications\n'
            "   and ONLY use results from these trusted domains:\n"
            f"   {', '.join(PREFERRED_DOMAINS)}\n"
            "3. Fetch the best matching product page\n"
            "4. Extract the specifications\n\n"
            "IMPORTANT: Only use results from the trusted domains listed above.\n"
            "If no trusted domain has this part, return exactly: {}\n\n"
            f"PRIORITY ATTRIBUTES (use these exact names where applicable):\n"
            f"  {', '.join(schema_attrs)}\n\n"
            f"Also extract ALL other specifications found on the page.\n"
            f"Maximize coverage — dimensions, material, finish, hardness, tolerances, "
            f"standards, compliance, and any other technical specs present.\n\n"
            f"UNIT RULE: {convert_note}\n\n"
            "RULES:\n"
            f"- All dimensional values must be in {unit_short}\n"
            "- For priority attributes, use the EXACT names listed above\n"
            "- For other attributes, use names as they appear in the source\n"
            "- Include Material, Hardness, Standard if present in the source\n"
            "- Omit attributes not found in the source\n"
            f"- CRITICAL: Return exactly ONE value per attribute for THIS specific part "
            f"({mfg_part_num}). If the page lists multiple sizes, pick the one matching "
            f"this part number or name: {part_name}. Never return comma-separated lists.\n\n"
            "RESPOND WITH ONLY a flat JSON object.\n"
            'You MUST include a "_source_url" key with the exact URL you fetched the data from.\n'
            "Do NOT include any explanation, markdown code fences, or text before/after the JSON.\n"
            f'Example: {{"_source_url": "https://example.com/part/123", '
            f'"Inner Diameter": "0.835 in", "Material": "18-8 Stainless Steel"}}'
        )

        raw = self._run_claude(
            prompt,
            allowed_tools=["WebSearch", "WebFetch"],
            timeout=300,
        )
        return self._parse_search_result(raw, part_class, "trusted")

    def _search_general(
        self,
        mfg_name: str,
        mfg_part_num: str,
        part_class: str,
        part_name: str,
        unit_of_measure: str,
    ) -> tuple[dict[str, str], str]:
        """Phase 2: General web search (any domain)."""
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)
        schema_attrs = get_schema(part_class)
        example = _example_json(unit_short)

        # Domains to skip (not useful for specs)
        skip = "youtube.com, amazon.com, ebay.com, alibaba.com, wikipedia.org, reddit.com, pinterest.com"

        prompt = (
            "You are a mechanical parts data extraction specialist.\n\n"
            "TASK: Find specifications for this part online and extract structured attributes.\n\n"
            f"Part Details:\n"
            f"  Manufacturer : {mfg_name}\n"
            f"  Part Number  : {mfg_part_num}\n"
            f"  Part Name    : {part_name}\n"
            f"  Part Class   : {part_class}\n"
            f"  Target Unit  : {unit_label}\n\n"
            "STEPS:\n"
            f'1. Search the web for "{mfg_name} {mfg_part_num} specifications"\n'
            f'2. If few results, also try: "{mfg_part_num} dimensions datasheet"\n'
            "3. Find a product page with detailed specs\n"
            f"4. SKIP these domains (no useful specs): {skip}\n"
            "5. Fetch the best product page and extract the specifications\n\n"
            f"REQUIRED ATTRIBUTE NAMES (use these exact names where applicable):\n"
            f"  {', '.join(schema_attrs)}\n\n"
            f"UNIT RULE: {convert_note}\n\n"
            "RULES:\n"
            f"- All dimensional values must be in {unit_short}\n"
            "- Use the EXACT attribute names listed above — do NOT invent synonyms\n"
            "- Include Material, Hardness, Standard if present in the source\n"
            "- Omit attributes not found in the source\n"
            '- If no specs found at all, return exactly: {}\n\n'
            "RESPOND WITH ONLY a flat JSON object.\n"
            'You MUST include a "_source_url" key with the exact URL you fetched the data from.\n'
            "Do NOT include any explanation, markdown code fences, or text before/after the JSON.\n"
            f'Example: {{"_source_url": "https://example.com/part/123", '
            f'"Inner Diameter": "0.835 in", "Material": "18-8 Stainless Steel"}}'
        )

        raw = self._run_claude(
            prompt,
            allowed_tools=["WebSearch", "WebFetch"],
            timeout=300,
        )
        return self._parse_search_result(raw, part_class, "general")

    def _fetch_and_extract(
        self,
        url: str,
        mfg_part_num: str,
        part_class: str,
        part_name: str,
        unit_of_measure: str,
    ) -> tuple[dict[str, str], str]:
        """Fetch a specific cached URL and extract attributes (no search needed)."""
        unit_label, unit_short, convert_note = _unit_instructions(unit_of_measure)
        schema_attrs = get_schema(part_class)

        prompt = (
            "You are a mechanical parts data extraction specialist.\n\n"
            f"TASK: Fetch this specific URL and extract part specifications:\n"
            f"  URL: {url}\n\n"
            f"Part Details:\n"
            f"  Part Number  : {mfg_part_num}\n"
            f"  Part Name    : {part_name}\n"
            f"  Part Class   : {part_class}\n"
            f"  Target Unit  : {unit_label}\n\n"
            f"REQUIRED ATTRIBUTE NAMES (use these exact names where applicable):\n"
            f"  {', '.join(schema_attrs)}\n\n"
            f"UNIT RULE: {convert_note}\n\n"
            "RULES:\n"
            f"- All dimensional values must be in {unit_short}\n"
            "- Use the EXACT attribute names listed above — do NOT invent synonyms\n"
            "- Include Material, Hardness, Standard if present in the source\n"
            "- Omit attributes not found in the source\n"
            '- If the page cannot be fetched or has no specs, return exactly: {}\n\n'
            "RESPOND WITH ONLY a flat JSON object.\n"
            "Do NOT include any explanation, markdown code fences, or text before/after the JSON."
        )

        raw = self._run_claude(
            prompt,
            allowed_tools=["WebFetch"],
            timeout=180,
        )

        if not raw:
            return {}, ""

        attrs = _parse_json(raw)
        cleaned = self._clean_attrs(attrs)
        if not cleaned:
            return {}, ""

        normalized = normalize_attrs(cleaned, part_class)
        return normalized, url

    def _parse_search_result(
        self, raw: str, part_class: str, label: str
    ) -> tuple[dict[str, str], str]:
        """Parse Claude's JSON response, extract _source_url, normalize attributes."""
        if not raw:
            return {}, ""

        attrs = _parse_json(raw)
        if not attrs:
            return {}, ""

        # Extract source URL before cleaning
        source_url = str(attrs.pop("_source_url", "")).strip()
        if not source_url:
            # Try other common key names Claude might use
            for key in list(attrs.keys()):
                if key.lower() in ("source_url", "source url", "url", "source", "page_url"):
                    source_url = str(attrs.pop(key, "")).strip()
                    break

        cleaned = self._clean_attrs(attrs)
        if not cleaned:
            return {}, ""

        normalized = normalize_attrs(cleaned, part_class)
        if source_url:
            print(f"    Source ({label}): {source_url}")
        return normalized, source_url

    @staticmethod
    def _clean_attrs(attrs: dict) -> dict:
        """Remove non-attribute keys and empty values."""
        skip_keys = {
            "part number", "part name", "part no", "part #",
            "source", "url", "source url", "source_url", "page_url",
            "_source_url",
        }
        return {
            k: v for k, v in attrs.items()
            if k.lower() not in skip_keys
            and str(v).strip().lower() not in (
                "", "none", "not specified", "n/a", "unknown", "null",
                "not available", "not rated",
            )
        }
