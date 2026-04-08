"""
Post-processing: deduplicate agent-extracted columns using LLM semantic matching.

Runs AFTER all parts are processed, BEFORE writing post-processing output files.
Only operates on agent-extra columns (not TC schema columns).

Deduplication requires BOTH conditions (AND — not OR):
  1. Values are identical across ALL parts where both columns are populated
  2. Column names are semantically equivalent (confirmed by LLM)

If either condition fails, the columns are NOT merged.
"""

import json
import re


async def deduplicate_agent_columns(
    results: list[dict],
    tc_attr_set: set[str],
    llm,
) -> tuple[list[dict], dict[str, str]]:
    """Find and merge duplicate agent-extracted columns.

    Returns (updated_results, merge_map) where merge_map is {removed_col: canonical_col}.
    Never touches TC schema columns. Never changes attribute values.
    """
    # Collect all agent-extra column names in order of first appearance
    agent_cols: list[str] = []
    seen: set[str] = set()
    for r in results:
        for k in r.get("attributes", {}).keys():
            if k not in tc_attr_set and k not in seen:
                agent_cols.append(k)
                seen.add(k)

    if len(agent_cols) < 2:
        return results, {}

    # Find candidate pairs: identical values in ALL parts where both are populated
    candidate_pairs: list[tuple[str, str]] = []
    for i, col_a in enumerate(agent_cols):
        for col_b in agent_cols[i + 1:]:
            # Find parts where both columns have non-empty values
            both_populated: list[tuple[str, str]] = []
            for r in results:
                attrs = r.get("attributes", {})
                val_a = attrs.get(col_a, "").strip()
                val_b = attrs.get(col_b, "").strip()
                if val_a and val_b:
                    both_populated.append((val_a, val_b))

            # Skip if no overlap (can't compare without shared data)
            if not both_populated:
                continue

            # AND condition: ALL overlapping parts must have identical values
            if all(va == vb for va, vb in both_populated):
                candidate_pairs.append((col_a, col_b))

    if not candidate_pairs:
        print("  [PostProc] No agent column pairs with identical values found.")
        return results, {}

    print(f"  [PostProc] {len(candidate_pairs)} candidate pair(s) with identical values — checking semantic equivalence...")

    # Batch LLM call to confirm semantic equivalence
    merge_decisions = await _confirm_semantic_equivalence(candidate_pairs, results, llm)

    if not merge_decisions:
        print("  [PostProc] LLM found no semantically equivalent pairs.")
        return results, {}

    # Resolve transitive chains (A→B, B→C → A→C, B→C)
    merge_map = _resolve_merge_chains(merge_decisions)

    # Apply merges to all result dicts
    updated = _apply_merges(results, merge_map)
    return updated, merge_map


async def _confirm_semantic_equivalence(
    candidate_pairs: list[tuple[str, str]],
    results: list[dict],
    llm,
) -> dict[str, str]:
    """Ask LLM to confirm which candidate pairs are semantically equivalent.

    Returns {removed_col: canonical_col} for confirmed merges.
    Uses a single batched LLM call for all candidate pairs (capped at 20).
    """
    pairs_to_check = candidate_pairs[:20]

    # Build prompt data with sample values for context
    pairs_data = []
    for col_a, col_b in pairs_to_check:
        sample_value = ""
        for r in results:
            attrs = r.get("attributes", {})
            if attrs.get(col_a) and attrs.get(col_b):
                sample_value = attrs[col_a]
                break
        pairs_data.append({
            "id": f"{col_a}|||{col_b}",
            "col_a": col_a,
            "col_b": col_b,
            "sample_value": sample_value,
        })

    prompt_json = json.dumps(pairs_data, ensure_ascii=False)

    try:
        raw = await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a mechanical engineering data specialist. "
                        "Determine if pairs of attribute column names refer to the same "
                        "physical property in an industrial parts database. "
                        "Be conservative — only confirm equivalence when you are certain. "
                        "Return ONLY valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"These column pairs have identical values across all parts where "
                        f"both appear. Determine if each pair refers to the SAME physical "
                        f"property (e.g., 'Thread Size' and 'Screw Size' both mean the "
                        f"nominal thread dimension). For confirmed equivalent pairs, choose "
                        f"the most descriptive and specific canonical name.\n\n"
                        f"Pairs to evaluate:\n{prompt_json}\n\n"
                        f"Return a JSON array:\n"
                        f"[{{\"id\": \"col_a|||col_b\", \"equivalent\": true/false, "
                        f"\"canonical\": \"best column name\"}}]\n"
                        f"Only include pairs you are CONFIDENT are equivalent. "
                        f"If uncertain, set equivalent=false."
                    ),
                },
            ],
            max_tokens=600,
            temperature=0,
        )

        # Parse response (strip markdown fences if present)
        clean = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
        decisions = json.loads(clean.strip())

        merge_decisions: dict[str, str] = {}
        for decision in decisions:
            if not decision.get("equivalent"):
                continue
            pair_id = decision.get("id", "")
            canonical = decision.get("canonical", "").strip()
            if "|||" not in pair_id or not canonical:
                continue
            col_a, col_b = pair_id.split("|||", 1)
            # The removed column is whichever is NOT the canonical name
            if canonical == col_a:
                merge_decisions[col_b] = col_a
            elif canonical == col_b:
                merge_decisions[col_a] = col_b
            else:
                # LLM chose a third name — keep col_a as canonical, drop col_b
                merge_decisions[col_b] = col_a

        return merge_decisions

    except Exception as e:
        print(f"  [PostProc] LLM semantic check failed: {e}")
        return {}


def _resolve_merge_chains(merge_map: dict[str, str]) -> dict[str, str]:
    """Resolve transitive merges: if A→B and B→C, then A→C and B→C."""
    resolved: dict[str, str] = {}
    for removed, kept in merge_map.items():
        canonical = kept
        # Follow the chain to the final canonical name
        while canonical in merge_map:
            canonical = merge_map[canonical]
        resolved[removed] = canonical
    return resolved


def _apply_merges(results: list[dict], merge_map: dict[str, str]) -> list[dict]:
    """Apply merge_map to all result dicts.

    For each removed column: move its value to the canonical column,
    but only if the canonical column is empty for that part (never overwrite).
    Values are never modified — only column names change.
    """
    updated: list[dict] = []
    for r in results:
        r_copy = dict(r)
        attrs = dict(r_copy.get("attributes", {}))
        for removed, canonical in merge_map.items():
            if removed in attrs:
                val = attrs.pop(removed)
                # Backfill canonical only if it has no value for this part
                if not attrs.get(canonical):
                    attrs[canonical] = val
        r_copy["attributes"] = attrs
        updated.append(r_copy)
    return updated
