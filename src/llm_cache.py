"""
LLM response cache to avoid redundant API calls.

Caches classification and extraction results. Thread-safe with atomic writes.
Cache keys include mfg_part_num to prevent collisions when different parts
share the same category page.
"""

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from src.shared import _atomic_write_json


CLASSIFY_TTL_DAYS = 90
EXTRACT_TTL_DAYS = 30


def _normalize(text: str) -> str:
    """Normalize text for cache key: lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class LLMCache:
    """Cache for LLM classification and extraction responses."""

    def __init__(self, cache_path: str | Path = "llm_cache.json"):
        self._path = Path(cache_path)
        self._lock = threading.Lock()
        self._data: dict = {"classify": {}, "extract": {}}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                if "classify" not in self._data:
                    self._data["classify"] = {}
                if "extract" not in self._data:
                    self._data["extract"] = {}
                # Purge expired entries on load
                self._purge_expired()
            except Exception:
                self._data = {"classify": {}, "extract": {}}

    def _purge_expired(self) -> None:
        """Remove expired entries on load to keep cache clean."""
        now = time.time()
        dirty = False
        for key in list(self._data["classify"]):
            ts = self._data["classify"][key].get("ts", 0)
            if now - ts > CLASSIFY_TTL_DAYS * 86400:
                del self._data["classify"][key]
                dirty = True
        for key in list(self._data["extract"]):
            ts = self._data["extract"][key].get("ts", 0)
            if now - ts > EXTRACT_TTL_DAYS * 86400:
                del self._data["extract"][key]
                dirty = True
        if dirty:
            self._save()

    def _save(self) -> None:
        _atomic_write_json(self._data, self._path)

    # ── Classification cache ──────────────────────────────────────────────

    def get_classification(self, input_text: str) -> str | None:
        """Look up cached classification. Returns class name or None."""
        key = _md5(_normalize(input_text))
        with self._lock:
            entry = self._data["classify"].get(key)
            if not entry:
                return None
            ts = entry.get("ts", 0)
            if time.time() - ts > CLASSIFY_TTL_DAYS * 86400:
                del self._data["classify"][key]
                return None
            return entry.get("class")

    def set_classification(self, input_text: str, part_class: str) -> None:
        """Cache a classification result."""
        key = _md5(_normalize(input_text))
        with self._lock:
            self._data["classify"][key] = {
                "class": part_class,
                "input_preview": input_text[:100],
                "ts": time.time(),
            }
            self._save()

    # ── Extraction cache ──────────────────────────────────────────────────

    def get_extraction(self, mfg_part_num: str, part_class: str,
                       content: str) -> dict | None:
        """Look up cached extraction. Returns attrs dict or None."""
        key = _md5(f"{mfg_part_num}|{part_class}|{content[:2000]}")
        with self._lock:
            entry = self._data["extract"].get(key)
            if not entry:
                return None
            ts = entry.get("ts", 0)
            if time.time() - ts > EXTRACT_TTL_DAYS * 86400:
                del self._data["extract"][key]
                return None
            return entry.get("attrs")

    def set_extraction(self, mfg_part_num: str, part_class: str,
                       content: str, attrs: dict) -> None:
        """Cache an extraction result."""
        key = _md5(f"{mfg_part_num}|{part_class}|{content[:2000]}")
        with self._lock:
            self._data["extract"][key] = {
                "attrs": attrs,
                "part": mfg_part_num,
                "class": part_class,
                "ts": time.time(),
            }
            self._save()

    # ── Management ────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Delete all cached data."""
        with self._lock:
            self._data = {"classify": {}, "extract": {}}
            if self._path.exists():
                self._path.unlink()

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            return {
                "classify_entries": len(self._data["classify"]),
                "extract_entries": len(self._data["extract"]),
                "path": str(self._path),
            }
