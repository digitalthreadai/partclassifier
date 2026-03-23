"""
Shared utilities used across the PartClassifier pipeline.

Consolidates duplicated code: manufacturer rotation, cache I/O with TTL,
and atomic file writes for Windows safety.
"""

import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path


# ── Cache I/O with TTL ──────────────────────────────────────────────────────

CACHE_TTL_DAYS = 30


def load_cache(cache_path: Path) -> dict[str, str]:
    """Load a URL cache, migrating old format and expiring stale entries.

    Old format: {"part_num": "url"}
    New format: {"part_num": {"url": "...", "ts": 1710000000}}
    Returns simple {part_num: url} dict for callers (TTL handled internally).
    """
    if not cache_path.exists():
        return {}
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    now = time.time()
    cutoff = now - (CACHE_TTL_DAYS * 86400)
    result: dict[str, str] = {}

    for key, value in raw.items():
        if isinstance(value, str):
            # Old format — migrate (assume fresh)
            result[key] = value
        elif isinstance(value, dict) and "url" in value:
            ts = value.get("ts", 0)
            if ts >= cutoff:
                result[key] = value["url"]
            # else: expired, skip
    return result


def save_cache(cache: dict[str, str], cache_path: Path) -> None:
    """Save URL cache with timestamps. Uses atomic write for Windows safety."""
    now = time.time()
    # Read existing to preserve timestamps for unchanged entries
    existing: dict = {}
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data: dict[str, dict] = {}
    for key, url in cache.items():
        # Preserve existing timestamp if URL unchanged
        if key in existing:
            old = existing[key]
            if isinstance(old, dict) and old.get("url") == url:
                data[key] = old
                continue
        data[key] = {"url": url, "ts": now}

    _atomic_write_json(data, cache_path)


def _atomic_write_json(data: dict, path: Path) -> None:
    """Write JSON atomically using tempfile + os.replace (Windows-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=path.stem
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── Manufacturer rotation ────────────────────────────────────────────────────

def rotate_manufacturers(parts: list[dict]) -> list[dict]:
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
