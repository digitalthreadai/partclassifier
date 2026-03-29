"""
Post-classification validation using class-blind attribute extraction + fit scoring.

Architecture: Classify → Blind Extract → Validate → Class-Aware Extract
  1. Initial classification (web content patterns + LLM fallback)
  2. Class-blind LLM extraction (no class context → unbiased attribute names)
  3. Score attribute overlap against CLASS_SCHEMAS for initial class + candidates
  4. Reclassify if a competitor clearly wins; abstain if uncertain
  5. Class-aware extraction runs with the validated class

All scoring is dynamic — no hardcoded class lists, attribute lists, or rules.
Universal attributes (in >90% of classes) are auto-detected and excluded from scoring.
"""

import json
from collections import Counter
from pathlib import Path

from src.attr_schema import (
    ALIASES,
    CLASS_SCHEMAS,
    CLASS_TREE_CHILDREN,
    get_schema,
    map_to_json_class,
)


# ── Dynamic universal attribute detection ────────────────────────────────────

def _compute_universal_attrs() -> set[str]:
    """Auto-detect attributes that appear in >90% of classes.

    These have zero discriminating power and are excluded from scoring.
    Adapts automatically to any customer's schema.
    """
    if not CLASS_SCHEMAS:
        return set()
    threshold = len(CLASS_SCHEMAS) * 0.9
    counts: Counter = Counter()
    for schema in CLASS_SCHEMAS.values():
        counts.update(a.lower() for a in schema)
    return {attr for attr, count in counts.items() if count >= threshold}


_UNIVERSAL_ATTRS: set[str] = _compute_universal_attrs()

# Minimum specific-attr matches needed to have any confidence
_MIN_EVIDENCE = 2

# Competitor must score at least this many MORE than initial to reclassify
_MIN_ADVANTAGE = 2


# ── Scoring ──────────────────────────────────────────────────────────────────

def score_class_fit(extracted_attrs: dict, candidate_class: str) -> int:
    """Count discriminating schema attrs present in extracted attrs.

    Normalizes both sides via ALIASES and lowercasing to handle
    "Inner Diameter" vs "ID" vs "inner diameter" etc.
    """
    schema = get_schema(candidate_class)
    if not schema:
        return 0
    schema_specific = {s.lower() for s in schema} - _UNIVERSAL_ATTRS
    # Normalize extracted keys through ALIASES (same as normalize_attrs does)
    extracted_canonical = set()
    for k in extracted_attrs.keys():
        k_lower = k.strip().lower()
        canonical = ALIASES.get(k_lower, k.strip())
        extracted_canonical.add(canonical.lower())
    return len(extracted_canonical & schema_specific)


# ── Candidate generation ─────────────────────────────────────────────────────

def get_candidate_classes(initial_class: str, part_name: str = "") -> list[str]:
    """Gather candidate classes: initial + family tree + part-name hints.

    Explores the class hierarchy (parent, siblings, children, grandchildren)
    and adds any classes suggested by part name keywords.
    """
    candidates = {initial_class}

    try:
        from src.class_extractor import _CHILD_PARENTS
        # Parent
        parents = _CHILD_PARENTS.get(initial_class, set())
        candidates.update(parents)
        # Siblings (parent's other children)
        for parent in parents:
            candidates.update(CLASS_TREE_CHILDREN.get(parent, []))
        # Children of initial
        candidates.update(CLASS_TREE_CHILDREN.get(initial_class, []))
        # Grandchildren
        for child in CLASS_TREE_CHILDREN.get(initial_class, []):
            candidates.update(CLASS_TREE_CHILDREN.get(child, []))
    except ImportError:
        pass

    # Part-name keyword candidates (all matches, not just first)
    if part_name:
        for hc in _hint_classes_from_name(part_name):
            mapped, _ = map_to_json_class(hc)
            candidates.add(mapped)
            # Also add its family tree
            try:
                from src.class_extractor import _CHILD_PARENTS
                for p in _CHILD_PARENTS.get(mapped, set()):
                    candidates.update(CLASS_TREE_CHILDREN.get(p, []))
                candidates.update(CLASS_TREE_CHILDREN.get(mapped, []))
            except ImportError:
                pass

    return [c for c in candidates if c in CLASS_SCHEMAS]


# ── Hints (candidate generation only, never override) ────────────────────────

_HINTS_CACHE: list[dict] | None = None


def _load_hints() -> list[dict]:
    """Load classification_hints.json once, cache for reuse."""
    global _HINTS_CACHE
    if _HINTS_CACHE is not None:
        return _HINTS_CACHE
    hints_path = Path(__file__).parent.parent / "schema" / "classification_hints.json"
    if not hints_path.exists():
        _HINTS_CACHE = []
        return _HINTS_CACHE
    try:
        with open(hints_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _HINTS_CACHE = data.get("hints", []) if isinstance(data, dict) else data
    except Exception:
        _HINTS_CACHE = []
    return _HINTS_CACHE


def _hint_classes_from_name(part_name: str) -> list[str]:
    """Return ALL matching hint classes from part name (not just first).

    Used only for candidate generation — never overrides classification directly.
    """
    hints = _load_hints()
    if not hints or not part_name:
        return []
    name_upper = part_name.upper()
    matches = []
    for entry in hints:
        for kw in entry.get("keywords", []):
            if kw in name_upper:
                matches.append(entry["class"])
                break  # one match per entry
    return matches


# ── Class-blind extraction ───────────────────────────────────────────────────

async def blind_extract(llm, content: str) -> dict[str, str]:
    """Class-blind attribute extraction — no class context, no priority list.

    Returns raw {attr_name: value} dict with unbiased attribute names.
    Lightweight prompt, runs before class-aware extraction to break the
    circular dependency between classification and extraction.
    """
    if not content or len(content) < 100:
        return {}
    text = content[:6000]
    try:
        raw = await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract ALL technical specifications from this product page. "
                        "Return ONLY valid JSON. No explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Extract every attribute name and value pair from this content.\n\n"
                        f"CONTENT:\n---\n{text}\n---\n\n"
                        f"Return flat JSON: {{\"Attribute Name\": \"value\", ...}}"
                    ),
                },
            ],
            max_tokens=1500,
            temperature=0,
        )
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return {}


# ── Main validation entry point ──────────────────────────────────────────────

def validate_classification(
    initial_class: str,
    blind_attrs: dict,
    part_name: str = "",
) -> tuple[str, str]:
    """Validate classification using class-blind extracted attrs.

    Returns (final_class, reason).
    Only reclassifies when there's strong evidence. Abstains when uncertain.

    Scoring logic:
    - Count how many discriminating (non-universal) schema attrs are in blind_attrs
    - Compare initial class score against all candidate classes
    - Reclassify only if competitor beats initial by >= _MIN_ADVANTAGE
    - Abstain (keep original) if best score < _MIN_EVIDENCE
    """
    if not blind_attrs or len(blind_attrs) < 3:
        return initial_class, "kept (too few blind attrs)"

    candidates = get_candidate_classes(initial_class, part_name)
    if not candidates:
        return initial_class, "kept (no candidates)"

    # Score all candidates
    scores = {cls: score_class_fit(blind_attrs, cls) for cls in candidates}
    initial_score = scores.get(initial_class, 0)
    best_class = max(scores, key=scores.get)
    best_score = scores[best_class]

    # ABSTAIN: if no candidate has enough evidence, keep original
    if best_score < _MIN_EVIDENCE:
        return initial_class, f"kept (low evidence, best={best_score})"

    # RECLASSIFY: only if competitor clearly beats initial
    if best_class != initial_class and best_score >= initial_score + _MIN_ADVANTAGE:
        return best_class, (
            f"reclassified: {best_class}={best_score} > {initial_class}={initial_score}"
        )

    # REFINE: if initial ties with a more specific child, prefer child
    if best_score == initial_score and best_class != initial_class:
        children = CLASS_TREE_CHILDREN.get(initial_class, [])
        if best_class in children:
            return best_class, f"refined to child: {best_class}"

    return initial_class, f"confirmed (score={initial_score})"
