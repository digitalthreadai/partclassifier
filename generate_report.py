"""
Generate HTML comparison report from benchmark results.

Usage:
    python generate_report.py

Reads all JSON files from benchmark_results/ and generates
benchmark_results/comparison_report.html
"""

import json
from pathlib import Path
from collections import defaultdict

RESULTS_DIR = Path(__file__).parent / "benchmark_results"
OUTPUT_HTML = RESULTS_DIR / "comparison_report.html"


def load_results() -> dict[str, dict]:
    """Load all benchmark JSON files."""
    results = {}
    for f in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        results[data["label"]] = data
    return results


def compute_stats(data: dict) -> dict:
    """Compute aggregate stats from benchmark data."""
    parts = data["parts"]
    total = len(parts)
    classified = sum(1 for p in parts if p["classification"])
    with_attrs = sum(1 for p in parts if p["attr_count"] > 0)
    total_attrs = sum(p["attr_count"] for p in parts)
    avg_attrs = total_attrs / with_attrs if with_attrs else 0
    errors = sum(1 for p in parts if p["error"])

    # By manufacturer
    by_mfg = defaultdict(lambda: {"total": 0, "with_attrs": 0, "total_attrs": 0, "errors": 0})
    for p in parts:
        mfg = p["mfg_name"]
        by_mfg[mfg]["total"] += 1
        if p["attr_count"] > 0:
            by_mfg[mfg]["with_attrs"] += 1
            by_mfg[mfg]["total_attrs"] += p["attr_count"]
        if p["error"]:
            by_mfg[mfg]["errors"] += 1

    # By source
    by_source = defaultdict(int)
    for p in parts:
        src = p.get("source_name") or "none"
        by_source[src] += 1

    # Classification distribution
    by_class = defaultdict(int)
    for p in parts:
        cls = p["classification"] or "Unclassified"
        by_class[cls] += 1

    return {
        "total": total,
        "classified": classified,
        "with_attrs": with_attrs,
        "total_attrs": total_attrs,
        "avg_attrs": round(avg_attrs, 1),
        "errors": errors,
        "elapsed_s": data.get("elapsed_s", 0),
        "by_mfg": dict(by_mfg),
        "by_source": dict(by_source),
        "by_class": dict(sorted(by_class.items(), key=lambda x: -x[1])),
    }


def generate_html(all_results: dict[str, dict]) -> str:
    labels = list(all_results.keys())
    stats = {label: compute_stats(data) for label, data in all_results.items()}

    # Collect all manufacturers across runs
    all_mfgs = set()
    for s in stats.values():
        all_mfgs.update(s["by_mfg"].keys())
    all_mfgs = sorted(all_mfgs)

    # Build per-part comparison (keyed by mfg_part_num)
    part_index = {}  # mfg_part_num -> {label: part_data}
    for label, data in all_results.items():
        for p in data["parts"]:
            key = p["mfg_part_num"]
            if key not in part_index:
                part_index[key] = {"mfg_name": p["mfg_name"], "mfg_part_num": key}
            part_index[key][label] = p

    # Header row for comparison table
    label_headers = "".join(f'<th colspan="2">{label.upper()}</th>' for label in labels)
    label_subheaders = "".join('<th>Class</th><th>Attrs</th>' for _ in labels)

    # Summary cards
    summary_cards = ""
    for label in labels:
        s = stats[label]
        model = all_results[label]["model"]
        elapsed_min = s["elapsed_s"] / 60
        throughput = s["total"] / (s["elapsed_s"] / 3600) if s["elapsed_s"] > 0 else 0
        summary_cards += f"""
        <div class="card">
            <div class="card-header">{label.upper()}</div>
            <div class="card-model">{model}</div>
            <div class="card-stats">
                <div class="stat">
                    <span class="stat-value">{s['total']}</span>
                    <span class="stat-label">Total Parts</span>
                </div>
                <div class="stat">
                    <span class="stat-value">{s['with_attrs']}</span>
                    <span class="stat-label">Parts w/ Attrs</span>
                </div>
                <div class="stat">
                    <span class="stat-value">{s['avg_attrs']}</span>
                    <span class="stat-label">Avg Attrs/Part</span>
                </div>
                <div class="stat">
                    <span class="stat-value">{s['total_attrs']}</span>
                    <span class="stat-label">Total Attributes</span>
                </div>
                <div class="stat">
                    <span class="stat-value">{s['errors']}</span>
                    <span class="stat-label">Errors</span>
                </div>
                <div class="stat">
                    <span class="stat-value">{elapsed_min:.0f}m</span>
                    <span class="stat-label">Runtime</span>
                </div>
                <div class="stat">
                    <span class="stat-value">{throughput:.0f}</span>
                    <span class="stat-label">Parts/Hour</span>
                </div>
            </div>
        </div>"""

    # Manufacturer comparison table
    mfg_rows = ""
    for mfg in all_mfgs:
        mfg_rows += f"<tr><td class='mfg-name'>{mfg}</td>"
        for label in labels:
            s = stats[label]
            m = s["by_mfg"].get(mfg, {"total": 0, "with_attrs": 0, "total_attrs": 0, "errors": 0})
            hit_rate = f"{m['with_attrs']}/{m['total']}" if m["total"] > 0 else "-"
            avg = round(m["total_attrs"] / m["with_attrs"], 1) if m["with_attrs"] > 0 else 0
            mfg_rows += f"<td>{hit_rate}</td><td>{avg}</td>"
        mfg_rows += "</tr>"

    # Source distribution
    all_sources = set()
    for s in stats.values():
        all_sources.update(s["by_source"].keys())
    all_sources = sorted(all_sources)

    source_rows = ""
    for src in all_sources:
        source_rows += f"<tr><td>{src}</td>"
        for label in labels:
            count = stats[label]["by_source"].get(src, 0)
            pct = round(100 * count / stats[label]["total"], 1) if stats[label]["total"] > 0 else 0
            source_rows += f"<td>{count} ({pct}%)</td>"
        source_rows += "</tr>"

    # Classification distribution (top 20)
    all_classes = set()
    for s in stats.values():
        all_classes.update(s["by_class"].keys())
    # Sort by total count across all labels
    class_totals = {}
    for cls in all_classes:
        class_totals[cls] = sum(stats[label]["by_class"].get(cls, 0) for label in labels)
    top_classes = sorted(class_totals.keys(), key=lambda c: -class_totals[c])[:30]

    class_rows = ""
    for cls in top_classes:
        class_rows += f"<tr><td>{cls}</td>"
        for label in labels:
            count = stats[label]["by_class"].get(cls, 0)
            class_rows += f"<td>{count}</td>"
        class_rows += "</tr>"

    # Per-part detail table (sample: show parts where models disagree on attr count)
    detail_rows = ""
    disagreements = []
    for key, pdata in sorted(part_index.items(), key=lambda x: x[1]["mfg_name"]):
        counts = [pdata.get(label, {}).get("attr_count", 0) for label in labels]
        if len(set(counts)) > 1 or any(c == 0 for c in counts):
            disagreements.append((key, pdata))

    for key, pdata in disagreements[:200]:  # limit to 200 rows
        detail_rows += f"<tr><td class='mfg-name'>{pdata['mfg_name']}</td><td>{pdata['mfg_part_num']}</td>"
        for label in labels:
            p = pdata.get(label, {})
            cls = p.get("classification", "-")
            ac = p.get("attr_count", 0)
            css = "zero-attrs" if ac == 0 else ("high-attrs" if ac >= 8 else "")
            detail_rows += f"<td>{cls}</td><td class='{css}'>{ac}</td>"
        detail_rows += "</tr>"

    # Build the full HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PartClassifier Benchmark — Model Comparison</title>
<style>
  :root {{
    --bg: #0a0a0f;
    --bg2: #12121a;
    --bg3: #1a1a25;
    --border: #2a2a3a;
    --text: #e8e8ed;
    --muted: #8888a0;
    --accent: #6c63ff;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #fbbf24;
    --blue: #60a5fa;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
  }}
  h1 {{
    font-size: 1.8rem;
    margin-bottom: 0.5rem;
    background: linear-gradient(135deg, var(--accent), var(--blue));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  h2 {{
    font-size: 1.3rem;
    margin: 2rem 0 1rem;
    color: var(--accent);
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.5rem;
  }}
  .subtitle {{
    color: var(--muted);
    margin-bottom: 2rem;
  }}
  .cards {{
    display: flex;
    gap: 1.5rem;
    flex-wrap: wrap;
    margin-bottom: 2rem;
  }}
  .card {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    flex: 1;
    min-width: 280px;
  }}
  .card-header {{
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 0.3rem;
  }}
  .card-model {{
    color: var(--muted);
    font-size: 0.85rem;
    margin-bottom: 1rem;
    font-family: 'JetBrains Mono', monospace;
  }}
  .card-stats {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
    gap: 0.75rem;
  }}
  .stat {{
    text-align: center;
  }}
  .stat-value {{
    display: block;
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--green);
  }}
  .stat-label {{
    display: block;
    font-size: 0.7rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--bg2);
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 2rem;
    font-size: 0.85rem;
  }}
  th {{
    background: var(--bg3);
    color: var(--accent);
    padding: 0.6rem 0.8rem;
    text-align: left;
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 2px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 1;
  }}
  td {{
    padding: 0.5rem 0.8rem;
    border-bottom: 1px solid var(--border);
    color: var(--text);
  }}
  tr:hover {{
    background: var(--bg3);
  }}
  .mfg-name {{
    font-weight: 600;
    color: var(--blue);
    white-space: nowrap;
  }}
  .zero-attrs {{
    color: var(--red);
    font-weight: 700;
  }}
  .high-attrs {{
    color: var(--green);
    font-weight: 600;
  }}
  .section {{
    margin-bottom: 3rem;
  }}
  .table-scroll {{
    overflow-x: auto;
    max-height: 600px;
    overflow-y: auto;
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  .filters {{
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }}
  .filter-btn {{
    background: var(--bg3);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 0.4rem 0.8rem;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.8rem;
    transition: all 0.2s;
  }}
  .filter-btn:hover, .filter-btn.active {{
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }}
  footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 0.75rem;
    text-align: center;
  }}
</style>
</head>
<body>

<h1>PartClassifier Benchmark Report</h1>
<p class="subtitle">Model comparison across {stats[labels[0]]['total']} semiconductor equipment parts from {len(all_mfgs)} manufacturers</p>

<div class="section">
  <h2>Summary</h2>
  <div class="cards">
    {summary_cards}
  </div>
</div>

<div class="section">
  <h2>Manufacturer Hit Rate</h2>
  <p style="color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem;">
    Parts with at least 1 extracted attribute / total parts. Avg = average attributes per successful part.
  </p>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th>Manufacturer</th>
          {''.join(f'<th>{l.upper()} Hit</th><th>{l.upper()} Avg</th>' for l in labels)}
        </tr>
      </thead>
      <tbody>{mfg_rows}</tbody>
    </table>
  </div>
</div>

<div class="section">
  <h2>Data Source Distribution</h2>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th>Source</th>
          {''.join(f'<th>{l.upper()}</th>' for l in labels)}
        </tr>
      </thead>
      <tbody>{source_rows}</tbody>
    </table>
  </div>
</div>

<div class="section">
  <h2>Classification Distribution (Top 30)</h2>
  <div class="table-scroll">
    <table>
      <thead>
        <tr>
          <th>Part Class</th>
          {''.join(f'<th>{l.upper()}</th>' for l in labels)}
        </tr>
      </thead>
      <tbody>{class_rows}</tbody>
    </table>
  </div>
</div>

<div class="section">
  <h2>Per-Part Detail (Disagreements &amp; Zero-Attr Parts)</h2>
  <p style="color: var(--muted); font-size: 0.85rem; margin-bottom: 1rem;">
    Showing parts where models produced different attribute counts or where any model found zero attributes.
    Sorted by manufacturer. Limited to first 200 rows.
  </p>
  <div class="table-scroll" style="max-height: 800px;">
    <table>
      <thead>
        <tr>
          <th>Manufacturer</th>
          <th>Part Number</th>
          {label_headers}
        </tr>
        <tr>
          <th></th>
          <th></th>
          {label_subheaders}
        </tr>
      </thead>
      <tbody>{detail_rows}</tbody>
    </table>
  </div>
</div>

<footer>
  Generated by PartClassifier Benchmark &mdash;
  {len(labels)} model(s) compared across {stats[labels[0]]['total']} parts from {len(all_mfgs)} manufacturers
</footer>

</body>
</html>"""
    return html


def main():
    results = load_results()
    if not results:
        print("No benchmark results found in benchmark_results/")
        return

    print(f"Found {len(results)} benchmark runs: {', '.join(results.keys())}")
    html = generate_html(results)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Report generated: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
