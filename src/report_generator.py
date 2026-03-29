"""
Generate a dark-themed HTML executive summary report for each classification run.

Produces output/run_summary.html with:
  - KPI cards (classified %, avg coverage, avg confidence)
  - Per-class table with averages
  - Confidence distribution (band breakdown)
  - Low-confidence parts list
  - Run details (timing, cache, tokens)
"""

import json
from datetime import datetime
from pathlib import Path


def generate_run_summary(
    results: list[dict],
    metrics_summary: dict,
    token_usage: dict,
    output_path: Path,
    input_file: str = "",
    model_name: str = "",
) -> str:
    """Generate HTML summary and write to output_path. Returns the file path."""
    total = len(results)
    if total == 0:
        return str(output_path)

    # ── Aggregate metrics ────────────────────────────────────────────────
    classified = sum(1 for r in results if r.get("part_class") not in ("Unclassified", "Error", ""))
    coverages = [r.get("extraction_coverage", 0) for r in results if r.get("extraction_coverage") is not None]
    reliabilities = [r.get("source_reliability", 0) for r in results if r.get("source_reliability") is not None]
    confidences = [r.get("classification_confidence", 0) for r in results if r.get("classification_confidence") is not None]
    lov_scores = [r.get("lov_compliance", 0) for r in results if r.get("lov_compliance") is not None]

    avg_coverage = sum(coverages) / len(coverages) if coverages else 0
    avg_reliability = sum(reliabilities) / len(reliabilities) if reliabilities else 0
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
    avg_lov = sum(lov_scores) / len(lov_scores) if lov_scores else 0

    # Per-class breakdown
    by_class: dict[str, list[dict]] = {}
    for r in results:
        cls = r.get("part_class", "Unknown")
        by_class.setdefault(cls, []).append(r)

    class_rows = []
    for cls in sorted(by_class.keys()):
        parts = by_class[cls]
        n = len(parts)
        ac = sum(p.get("extraction_coverage", 0) for p in parts) / n
        ar = sum(p.get("source_reliability", 0) for p in parts) / n
        cc = sum(p.get("classification_confidence", 0) for p in parts) / n
        class_rows.append({"class": cls, "count": n, "coverage": ac, "reliability": ar, "confidence": cc})

    # Confidence distribution bands
    bands = {"90-100%": 0, "70-89%": 0, "50-69%": 0, "<50%": 0}
    for c in confidences:
        if c >= 90: bands["90-100%"] += 1
        elif c >= 70: bands["70-89%"] += 1
        elif c >= 50: bands["50-69%"] += 1
        else: bands["<50%"] += 1

    # Low-confidence parts (any metric < 50%)
    low_conf = []
    for r in results:
        ec = r.get("extraction_coverage", 0)
        cc = r.get("classification_confidence", 0)
        sr = r.get("source_reliability", 0)
        if ec < 50 or cc < 50 or sr < 50:
            pn = r.get("part", {}).get("Manufacturer Part Number", "")
            name = r.get("part", {}).get("Part Name", "")
            low_conf.append({
                "pn": pn, "name": name[:50], "class": r.get("part_class", ""),
                "coverage": ec, "reliability": sr, "confidence": cc,
            })

    # Tokens
    total_tokens = token_usage.get("total_tokens", 0)
    avg_tokens = total_tokens / total if total > 0 else 0

    # Timing
    elapsed = metrics_summary.get("elapsed_seconds", 0)
    per_part = elapsed / total if total > 0 else 0

    # ── Build HTML ───────────────────────────────────────────────────────
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Run Summary - PartClassifier</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0a0a0f;--bg2:#12121a;--bg3:#1a1a2e;--accent:#6c63ff;--accent2:#00d4aa;--text:#e8e8ed;--muted:#8888a0;--border:#2a2a3e;--green:#4ade80;--amber:#fb923c;--red:#f87171;--radius:10px;--shadow:0 4px 24px rgba(0,0,0,.4)}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:2rem}}
.container{{max-width:1200px;margin:0 auto}}
h1{{font-size:2rem;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:.5rem}}
.subtitle{{color:var(--muted);margin-bottom:2rem}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-bottom:2rem}}
.kpi{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:1.5rem;text-align:center}}
.kpi .value{{font-size:2.2rem;font-weight:700;font-family:'JetBrains Mono',monospace}}
.kpi .label{{color:var(--muted);font-size:.85rem;margin-top:.3rem}}
.green{{color:var(--green)}}.amber{{color:var(--amber)}}.red{{color:var(--red)}}.purple{{color:var(--accent)}}
table{{width:100%;border-collapse:collapse;margin-bottom:2rem;background:var(--bg2);border-radius:var(--radius);overflow:hidden}}
th{{background:var(--bg3);padding:.75rem 1rem;text-align:left;font-weight:600;font-size:.85rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
td{{padding:.65rem 1rem;border-top:1px solid var(--border);font-size:.9rem}}
tr:hover td{{background:rgba(108,99,255,.05)}}
.section{{margin-bottom:2.5rem}}
.section h2{{font-size:1.3rem;margin-bottom:1rem;padding-bottom:.5rem;border-bottom:1px solid var(--border)}}
.bar-row{{display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem}}
.bar-label{{width:80px;text-align:right;font-size:.85rem;color:var(--muted)}}
.bar-track{{flex:1;height:24px;background:var(--bg3);border-radius:4px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:4px;display:flex;align-items:center;padding-left:.5rem;font-size:.75rem;font-weight:600;min-width:30px}}
.bar-fill.high{{background:var(--green)}}.bar-fill.med{{background:var(--amber)}}.bar-fill.low{{background:var(--red)}}.bar-fill.top{{background:var(--accent)}}
.detail-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem}}
.detail{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:1rem}}
.detail .dl{{color:var(--muted);font-size:.8rem}}.detail .dv{{font-family:'JetBrains Mono',monospace;font-size:1.1rem;margin-top:.25rem}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:600}}
.badge-green{{background:rgba(74,222,128,.15);color:var(--green)}}
.badge-amber{{background:rgba(251,146,60,.15);color:var(--amber)}}
.badge-red{{background:rgba(248,113,113,.15);color:var(--red)}}
footer{{text-align:center;color:var(--muted);font-size:.8rem;margin-top:3rem;padding-top:1rem;border-top:1px solid var(--border)}}
</style>
</head>
<body>
<div class="container">

<h1>PartClassifier Run Summary</h1>
<p class="subtitle">{now} &middot; {input_file} &middot; {model_name} &middot; {total} parts</p>

<div class="kpi-grid">
  <div class="kpi"><div class="value purple">{classified}/{total}</div><div class="label">Parts Classified ({classified/total*100:.0f}%)</div></div>
  <div class="kpi"><div class="value {_color_class(avg_coverage)}">{avg_coverage:.1f}%</div><div class="label">Avg Extraction Coverage</div></div>
  <div class="kpi"><div class="value {_color_class(avg_reliability)}">{avg_reliability:.1f}%</div><div class="label">Avg Source Reliability</div></div>
  <div class="kpi"><div class="value {_color_class(avg_confidence)}">{avg_confidence:.1f}%</div><div class="label">Avg Classification Confidence</div></div>
  <div class="kpi"><div class="value {_color_class(avg_lov)}">{avg_lov:.1f}%</div><div class="label">Avg LOV Compliance</div></div>
</div>

<div class="section">
<h2>Per-Class Breakdown</h2>
<table>
<tr><th>Class</th><th>Parts</th><th>Extraction Coverage</th><th>Source Reliability</th><th>Classification Confidence</th></tr>
{"".join(_class_row(cr) for cr in class_rows)}
</table>
</div>

<div class="section">
<h2>Classification Confidence Distribution</h2>
{_bands_html(bands, total)}
</div>

{"" if not low_conf else _low_conf_section(low_conf)}

<div class="section">
<h2>Run Details</h2>
<div class="detail-grid">
  <div class="detail"><div class="dl">Total Time</div><div class="dv">{elapsed:.1f}s ({per_part:.1f}s/part)</div></div>
  <div class="detail"><div class="dl">LLM Calls</div><div class="dv">{metrics_summary.get('total_llm_calls', 0)}</div></div>
  <div class="detail"><div class="dl">Cache Hits</div><div class="dv">{metrics_summary.get('cache_hits_classify', 0) + metrics_summary.get('cache_hits_extract', 0)}</div></div>
  <div class="detail"><div class="dl">Total Tokens</div><div class="dv">{total_tokens:,}</div></div>
  <div class="detail"><div class="dl">Avg Tokens/Part</div><div class="dv">{avg_tokens:,.0f}</div></div>
  <div class="detail"><div class="dl">Model</div><div class="dv">{model_name}</div></div>
</div>
</div>

<footer>Generated by PartClassifier v2.0 &middot; {now}</footer>

</div>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"  -> {output_path}")
    return str(output_path)


# ── HTML helpers ─────────────────────────────────────────────────────────────

def _color_class(val: float) -> str:
    if val >= 80: return "green"
    if val >= 50: return "amber"
    return "red"


def _badge(val: float) -> str:
    cls = "badge-green" if val >= 80 else "badge-amber" if val >= 50 else "badge-red"
    return f'<span class="badge {cls}">{val:.1f}%</span>'


def _class_row(cr: dict) -> str:
    return (
        f'<tr><td>{cr["class"]}</td><td>{cr["count"]}</td>'
        f'<td>{_badge(cr["coverage"])}</td>'
        f'<td>{_badge(cr["reliability"])}</td>'
        f'<td>{_badge(cr["confidence"])}</td></tr>\n'
    )


def _bands_html(bands: dict, total: int) -> str:
    colors = {"90-100%": "top", "70-89%": "high", "50-69%": "med", "<50%": "low"}
    rows = ""
    for label, count in bands.items():
        pct = count / total * 100 if total > 0 else 0
        c = colors[label]
        rows += (
            f'<div class="bar-row">'
            f'<div class="bar-label">{label}</div>'
            f'<div class="bar-track"><div class="bar-fill {c}" style="width:{max(pct, 3):.0f}%">{count}</div></div>'
            f'</div>\n'
        )
    return rows


def _low_conf_section(low_conf: list[dict]) -> str:
    rows = ""
    for p in low_conf[:20]:  # limit to 20
        rows += (
            f'<tr><td>{p["pn"]}</td><td>{p["name"]}</td><td>{p["class"]}</td>'
            f'<td>{_badge(p["coverage"])}</td>'
            f'<td>{_badge(p["reliability"])}</td>'
            f'<td>{_badge(p["confidence"])}</td></tr>\n'
        )
    return f"""
<div class="section">
<h2>Low-Confidence Parts (any metric &lt;50%)</h2>
<table>
<tr><th>Part #</th><th>Name</th><th>Class</th><th>Coverage</th><th>Reliability</th><th>Confidence</th></tr>
{rows}
</table>
</div>
"""
