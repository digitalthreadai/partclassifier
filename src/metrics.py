"""
Run metrics tracker for monitoring quality, cost, and cache effectiveness.

Tracks per-run metrics and appends to a history file for trend analysis.
Prints a summary at end of each run.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.shared import _atomic_write_json


@dataclass
class RunMetrics:
    """Accumulates metrics during a pipeline run."""

    # Quality
    parts_total: int = 0
    parts_classified: int = 0
    parts_with_attrs: int = 0
    zero_attr_parts: int = 0
    total_attrs: int = 0

    # Cache
    cache_hits_classify: int = 0
    cache_hits_extract: int = 0

    # Regex
    regex_extract_count: int = 0          # parts where regex found any attrs
    regex_llm_agreed: int = 0             # attrs where regex == LLM
    regex_llm_disagreed: int = 0          # attrs where regex != LLM
    regex_total_attrs: int = 0            # total regex attrs across all parts

    # LLM calls
    total_llm_calls: int = 0
    classify_llm_calls: int = 0
    extract_llm_calls: int = 0

    # Timing
    start_time: float = field(default_factory=time.time)

    def record_part(self, *, classified: bool, attr_count: int) -> None:
        self.parts_total += 1
        if classified:
            self.parts_classified += 1
        if attr_count > 0:
            self.parts_with_attrs += 1
            self.total_attrs += attr_count
        else:
            self.zero_attr_parts += 1

    def record_cache_hit(self, cache_type: str) -> None:
        if cache_type == "classify":
            self.cache_hits_classify += 1
        elif cache_type == "extract":
            self.cache_hits_extract += 1

    def record_llm_call(self, call_type: str) -> None:
        self.total_llm_calls += 1
        if call_type == "classify":
            self.classify_llm_calls += 1
        elif call_type == "extract":
            self.extract_llm_calls += 1

    def record_regex(self, regex_count: int, agreement: dict | None = None) -> None:
        if regex_count > 0:
            self.regex_extract_count += 1
            self.regex_total_attrs += regex_count
        if agreement:
            self.regex_llm_agreed += agreement.get("agreed", 0)
            self.regex_llm_disagreed += agreement.get("disagreed", 0)

    def summary(self) -> dict:
        elapsed = time.time() - self.start_time
        n = max(self.parts_total, 1)
        return {
            "parts_total": self.parts_total,
            "parts_classified": self.parts_classified,
            "classify_rate": f"{100 * self.parts_classified / n:.0f}%",
            "parts_with_attrs": self.parts_with_attrs,
            "attr_rate": f"{100 * self.parts_with_attrs / n:.0f}%",
            "avg_attrs_per_part": round(self.total_attrs / n, 1),
            "zero_attr_parts": self.zero_attr_parts,
            "cache_hits_classify": self.cache_hits_classify,
            "cache_hits_extract": self.cache_hits_extract,
            "total_cache_hits": self.cache_hits_classify + self.cache_hits_extract,
            "regex_parts_with_data": self.regex_extract_count,
            "regex_total_attrs": self.regex_total_attrs,
            "regex_llm_agreed": self.regex_llm_agreed,
            "regex_llm_disagreed": self.regex_llm_disagreed,
            "regex_agreement_rate": (
                f"{100 * self.regex_llm_agreed / max(self.regex_llm_agreed + self.regex_llm_disagreed, 1):.0f}%"
            ),
            "total_llm_calls": self.total_llm_calls,
            "classify_llm_calls": self.classify_llm_calls,
            "extract_llm_calls": self.extract_llm_calls,
            "elapsed_seconds": round(elapsed, 1),
            "seconds_per_part": round(elapsed / n, 1),
        }

    def print_summary(self) -> None:
        s = self.summary()
        print(f"\n{'=' * 60}")
        print(f"  Run Metrics Summary")
        print(f"{'=' * 60}")
        print(f"  Parts: {s['parts_total']}")
        print(f"  Classified: {s['parts_classified']} ({s['classify_rate']})")
        print(f"  With attrs: {s['parts_with_attrs']} ({s['attr_rate']}), avg {s['avg_attrs_per_part']}/part")
        print(f"  Zero attrs: {s['zero_attr_parts']}")
        print(f"  Cache hits: {s['total_cache_hits']} (classify={s['cache_hits_classify']}, extract={s['cache_hits_extract']})")
        print(f"  Regex: {s['regex_parts_with_data']} parts with data, {s['regex_total_attrs']} total attrs")
        print(f"  Regex/LLM agreement: {s['regex_llm_agreed']} agreed, {s['regex_llm_disagreed']} disagreed ({s['regex_agreement_rate']})")
        print(f"  LLM calls: {s['total_llm_calls']} (classify={s['classify_llm_calls']}, extract={s['extract_llm_calls']})")
        print(f"  Time: {s['elapsed_seconds']}s ({s['seconds_per_part']}s/part)")

    def save_to_history(self, history_path: str | Path = "metrics_history.json") -> None:
        """Append this run's metrics to the history file."""
        path = Path(history_path)
        history: list = []
        if path.exists():
            try:
                history = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                history = []

        entry = self.summary()
        entry["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        history.append(entry)

        _atomic_write_json(history, path)
