"""
Post-processing: deduplicate agent-extracted columns using LLM semantic matching.

Runs AFTER all parts are processed, BEFORE writing post-processing output files.
Only operates on agent-extra columns (not TC schema columns).

Two-phase per-part deduplication:
  Phase A (delete): For each part, if an agent column's value equals a TC column's
    value on THAT SAME PART, and LLM confirms they refer to the same property,
    the agent column is deleted from all parts.
  Phase B (merge): For remaining agent columns, if two agent columns have the same
    value on the same part, and LLM confirms semantic equivalence, they are merged.

Values are compared within a single part only — no cross-part comparison.
"""

import json
import re


async def deduplicate_agent_columns(
    results: list[dict],
    tc_attr_set: set[str],
    llm,
) -> tuple[list[dict], dict[str, str]]:
    """Deduplicate agent-extracted columns using per-part value matching + LLM confirmation.

    Returns (updated_results, action_map) where action_map is
    {removed_col: canonical_col} for merges and {deleted_col: "DELETED"} for deletions.
    Never touches TC schema columns. Never changes attribute values.
    """
    # Collect agent-extra column names in order of first appearance
    agent_cols: list[str] = []
    seen: set[str] = set()
    for r in results:
        for k in r.get("attributes", {}).keys():
            if k not in tc_attr_set and k not in seen:
                agent_cols.append(k)
                seen.add(k)

    if not agent_cols:
        return results, {}

    # ── Phase A: agent-vs-TC ─────────────────────────────────────────────────
    # Per part: if agent col value == TC col value on THAT SAME PART → candidate
    agent_tc_seen: set[tuple[str, str]] = set()
    for r in results:
        attrs = r.get("attributes", {})
        for agent_col in agent_cols:
            agent_val = attrs.get(agent_col, "").strip()
            if not agent_val:
                continue
            for tc_col in tc_attr_set:
                tc_val = attrs.get(tc_col, "").strip()
                if tc_val and agent_val == tc_val:
                    agent_tc_seen.add((agent_col, tc_col))

    cols_to_delete: set[str] = set()
    if agent_tc_seen:
        print(f"  [PostProc] {len(agent_tc_seen)} agent-vs-TC candidate(s) — checking semantic equivalence...")
        cols_to_delete = await _confirm_agent_tc_duplicates(list(agent_tc_seen), llm)
        if cols_to_delete:
            print(f"  [PostProc] Deleting {len(cols_to_delete)} agent column(s) that duplicate TC attrs: {sorted(cols_to_delete)}")
        else:
            print("  [PostProc] LLM found no agent-TC duplicates to delete.")

    # ── Phase B: agent-vs-agent ──────────────────────────────────────────────
    # Per part: if two remaining agent cols have the same value on the same part → candidate
    remaining = [c for c in agent_cols if c not in cols_to_delete]
    agent_agent_seen: set[tuple[str, str]] = set()
    for r in results:
        attrs = r.get("attributes", {})
        for i, col_a in enumerate(remaining):
            val_a = attrs.get(col_a, "").strip()
            if not val_a:
                continue
            for col_b in remaining[i + 1:]:
                val_b = attrs.get(col_b, "").strip()
                if val_b and val_a == val_b:
                    # Store in canonical order (alphabetical) to avoid duplicate pairs
                    pair = (col_a, col_b) if col_a < col_b else (col_b, col_a)
                    agent_agent_seen.add(pair)

    merge_map: dict[str, str] = {}
    if agent_agent_seen:
        print(f"  [PostProc] {len(agent_agent_seen)} agent-vs-agent candidate pair(s) — checking semantic equivalence...")
        merge_decisions = await _confirm_semantic_equivalence(list(agent_agent_seen), results, llm)
        if merge_decisions:
            merge_map = _resolve_merge_chains(merge_decisions)
            print(f"  [PostProc] Merging {len(merge_map)} agent column pair(s): {merge_map}")
        else:
            print("  [PostProc] LLM found no agent-agent pairs to merge.")

    if not cols_to_delete and not merge_map:
        return results, {}

    updated = _apply_deletions_and_merges(results, cols_to_delete, merge_map)
    action_map: dict[str, str] = {c: "DELETED (TC duplicate)" for c in cols_to_delete}
    action_map.update(merge_map)
    return updated, action_map


async def _confirm_agent_tc_duplicates(
    candidate_pairs: list[tuple[str, str]],
    llm,
) -> set[str]:
    """Ask LLM which agent columns are true duplicates of their paired TC columns.

    candidate_pairs: list of (agent_col, tc_col) where values matched on the same part.
    Returns set of agent_col names confirmed as duplicates (to be deleted).
    """
    pairs_data = [
        {"id": f"{agent_col}|||{tc_col}", "agent_col": agent_col, "tc_col": tc_col}
        for agent_col, tc_col in candidate_pairs[:20]
    ]
    prompt_json = json.dumps(pairs_data, ensure_ascii=False)

    try:
        raw = await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an industrial parts classification specialist. "
                        "Determine if agent-extracted attribute names are duplicates of "
                        "standard Teamcenter (TC) schema attribute names. "
                        "Be conservative — only confirm when you are certain. "
                        "Return ONLY valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "For each pair, the agent_col is an informal/abbreviated name "
                        "extracted by an AI agent, and the tc_col is the official TC schema "
                        "attribute name. They had identical values on the same part.\n\n"
                        "Determine if each agent_col is truly a duplicate of the tc_col "
                        "(i.e., they describe the same physical property). "
                        "Examples: 'ID' duplicates 'Inner Diameter', 'OD' duplicates "
                        "'Outer Diameter', 'T' duplicates 'Thickness'.\n\n"
                        f"Pairs:\n{prompt_json}\n\n"
                        "Return a JSON array:\n"
                        "[{\"id\": \"agent_col|||tc_col\", \"duplicate\": true/false}]\n"
                        "Only mark duplicate=true when certain."
                    ),
                },
            ],
            max_tokens=400,
            temperature=0,
        )

        clean = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
        decisions = json.loads(clean.strip())

        cols_to_delete: set[str] = set()
        for decision in decisions:
            if not decision.get("duplicate"):
                continue
            pair_id = decision.get("id", "")
            if "|||" not in pair_id:
                continue
            agent_col, _ = pair_id.split("|||", 1)
            cols_to_delete.add(agent_col)
        return cols_to_delete

    except Exception as e:
        print(f"  [PostProc] LLM agent-TC duplicate check failed: {e}")
        return set()


async def _confirm_semantic_equivalence(
    candidate_pairs: list[tuple[str, str]],
    results: list[dict],
    llm,
) -> dict[str, str]:
    """Ask LLM to confirm which agent-vs-agent pairs are semantically equivalent.

    Returns {removed_col: canonical_col} for confirmed merges.
    Uses a single batched LLM call (capped at 20 pairs).
    """
    pairs_to_check = candidate_pairs[:20]

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
                        "You are an industrial parts classification specialist. "
                        "Determine if pairs of attribute column names refer to the same "
                        "physical property in an industrial parts database. "
                        "Be conservative — only confirm equivalence when you are certain. "
                        "Return ONLY valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"These agent-extracted column pairs had identical values on the same "
                        f"part. Determine if each pair refers to the SAME physical property "
                        f"(e.g., 'Thread Size' and 'Screw Size' both mean the nominal thread "
                        f"dimension). For confirmed equivalent pairs, choose the most "
                        f"descriptive and specific canonical name.\n\n"
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
        while canonical in merge_map:
            canonical = merge_map[canonical]
        resolved[removed] = canonical
    return resolved


def _apply_deletions_and_merges(
    results: list[dict],
    cols_to_delete: set[str],
    merge_map: dict[str, str],
) -> list[dict]:
    """Apply deletions (Phase A) and merges (Phase B) to all result dicts.

    Deletions: agent column removed entirely — no value transfer.
    Merges: removed column's value backfills canonical only if canonical is empty.
    Values are never modified — only keys change.
    """
    updated: list[dict] = []
    for r in results:
        r_copy = dict(r)
        attrs = dict(r_copy.get("attributes", {}))

        # Phase A: delete agent cols that duplicate TC cols
        for col in cols_to_delete:
            attrs.pop(col, None)

        # Phase B: merge agent-agent duplicates
        for removed, canonical in merge_map.items():
            if removed in attrs:
                val = attrs.pop(removed)
                if not attrs.get(canonical):
                    attrs[canonical] = val

        r_copy["attributes"] = attrs
        updated.append(r_copy)
    return updated
