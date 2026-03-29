# Part Classification Agent

A production-grade AI agent that reads mechanical parts from Excel, searches distributor APIs and the web for specifications, classifies each part into 93 categories using a classify-then-blind-extract-then-validate-then-extract architecture, and writes per-class Excel output files with TC Class ID -- ready for Teamcenter PLM import. Includes a PLMXML-to-JSON converter for importing Teamcenter classification hierarchies.

**7,031 LOC | 18 modules | 9 LLM providers | 3 distributor APIs | 93 part classes | 46 attributes | 500+ aliases | class_validator.py | classification_hints.json | configurable aliases.json**

**Three execution modes:**

| Mode | Entry point | LLM access | Best for |
|---|---|---|---|
| **API Key CLI** | `main.py` | Groq / OpenAI / Anthropic / Azure / Bedrock / Ollama / Custom | Direct API key users |
| **Claude Code CLI** | `main_cc.py` | `claude` CLI (zero API keys, parallel workers) | Enterprise, large batches (1K-20K+) |
| **Streamlit Web UI** | `app.py` | Any API key provider | Non-technical users, demos |

---

## Quick Start

### Option A: Claude Code CLI (no API keys)

If you have [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed:

```bash
git clone https://github.com/digitalthreadai/partclassifier.git
cd partclassifier
pip install -r requirements.txt
python main_cc.py
```

No `.env` file or API keys needed. Uses `claude` CLI on PATH with any configured backend.

### Option B: API Key mode

```bash
git clone https://github.com/digitalthreadai/partclassifier.git
cd partclassifier
pip install -r requirements.txt
cp .env.example .env              # then set LLM_PROVIDER and LLM_API_KEY
streamlit run app.py
```

Open http://localhost:8501, configure your LLM provider in the sidebar, and click **Run Classification**.

### Option C: Command line (API key)

```bash
python main.py
python main.py --no-cache          # bypass LLM cache
python main.py --clear-cache       # delete cache before run
python main.py --fresh             # clear cache + progress, start fresh
```

---

## Pipeline (7 Steps)

```
1. Read Excel input
       |
2. Multi-tier search (APIs -> Stealth -> Cache -> DuckDuckGo)
       |
3. Initial classify (web content patterns -> LLM fallback)
       |
4. Class-blind LLM extraction (no class bias -- extracts ALL specs)
       |
5. Validate classification (attribute-fit scoring against CLASS_SCHEMAS)
       |
6. Class-aware LLM extraction (with validated class + regex pre-extraction)
       |
7. Write per-class Excel output with TC Class ID + HTML executive summary
```

For each part in the input Excel:

1. **Searches** for specs via distributor APIs first (DigiKey OAuth2, Mouser API key, McMaster-Carr mTLS), falling back to CloakBrowser stealth scraping, then DuckDuckGo web search with curl_cffi (Chrome 124 TLS fingerprint).
2. **Cleans** content via HTML table extraction and smart truncation (3K/5K/8K char limits) to prioritize specs over navigation boilerplate.
3. **Classifies** the part deterministically from web content (breadcrumbs, category labels, URL paths). Falls back to LLM classification only when inconclusive. 93 part classes supported (via JSON schema with Teamcenter-compatible hierarchical class tree).
4. **Class-blind LLM extraction** extracts ALL specs without class bias, breaking the circular dependency between classification and extraction.
5. **Validates** classification via attribute-fit scoring against CLASS_SCHEMAS. Dynamically computes universal attrs (>90% of classes). Reclassifies only with strong evidence (MIN_ADVANTAGE=2). Abstains when uncertain.
6. **Class-aware extraction** with validated class + regex pre-extraction + unit handling. Supports inches, mm, or as-is mode (preserves original units when not specified).
7. **Normalizes** attributes via 500+ alias mappings to canonical names and **writes** one output Excel file per part class into the `output/` folder, with TC Class ID and schema-ordered columns. Also generates an HTML executive summary report (`output/run_summary.html`).

---

## Setup

### 1. Prerequisites

- **Python 3.11+** ([python.org](https://www.python.org/downloads/))
- **For API Key mode:** An API key from one of the 9 supported LLM providers
- **For Claude Code CLI mode:** [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and configured

### 2. Install

```bash
git clone https://github.com/digitalthreadai/partclassifier.git
cd partclassifier
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

### 3. Configure LLM provider (API key mode only)

```bash
cp .env.example .env
```

**Groq (free, recommended to start):**
```env
LLM_PROVIDER=groq
LLM_API_KEY=gsk_your_groq_key_here
```

See [SITECONFIGURATIONS.md](SITECONFIGURATIONS.md) for all 9 provider configurations.

### 4. Prepare input Excel

Place your file at `input/PartClassifierInput.xlsx` with columns: Part Number, Part Name, Manufacturer Part Number, Manufacturer Name, Unit of Measure.

### 5. Classification Schema (optional customization)

The JSON-based schema is the primary schema source:

- **`schema/Classes.json`** -- Teamcenter-compatible hierarchical class tree with 93 classes. Each class has ICM-format IDs matching Teamcenter classid, parent-child relationships with attribute inheritance, and class aliases for web content classification.
- **`schema/Attributes.json`** -- Attribute dictionary with 46 attributes using 5-digit numeric IDs matching Teamcenter attribute IDs. Includes name, shortname, aliases, unitOfMeasure (multi-value array), range, LOV values, and keyLOVID.

Attribute inheritance: child classes automatically inherit all ancestor attributes. LOV normalization: extracted values are matched to Teamcenter LOV entries (e.g., "Stainless Steel" maps to "StainlessSteel").

To generate JSON schema files from Teamcenter PLMXML exports, use the included converter:

```bash
python plmxml_to_json.py --plmxml export.xml --sml attributes.xml --output schema/
```

- **`schema/aliases.json`** (auto-generated, human-editable) -- configurable alias mappings that override all other sources:
  - `attribute_aliases`: alternate names/abbreviations per attribute (e.g., "ID", "Bore" → "Inner Diameter")
  - `class_aliases`: alternate class names

- **`schema/classification_hints.json`** -- Part-name keyword to class mappings for candidate generation during validation

Generate `aliases.json` and `classification_hints.json` using the LLM schema generator (same `.env` config as `main.py`):

```bash
python generate_schema.py              # generate both aliases.json + classification_hints.json
python generate_schema.py --aliases    # generate aliases.json only
python generate_schema.py --hints      # generate classification_hints.json only
python generate_schema.py --merge      # fill gaps, keep manual edits
```

### 6. Run

```bash
streamlit run app.py             # Web UI
python main.py                   # API key CLI
python main_cc.py                # Claude Code CLI (no API keys)
python main_cc.py --workers 8    # Claude Code CLI with 8 parallel workers
```

---

## LLM Configuration

10 scenarios across 9 providers:

| Scenario | LLM_PROVIDER | Required Vars | Notes |
|----------|-------------|---------------|-------|
| Groq (free, fast) | `groq` | `LLM_API_KEY` | Default. Free tier: 100K tokens/day |
| OpenAI (GPT-4o) | `openai` | `LLM_API_KEY` | Paid |
| Anthropic (Claude) | `anthropic` | `LLM_API_KEY` | Direct Anthropic API |
| Azure + GPT | `azure_openai` | `LLM_API_KEY`, `AZURE_OPENAI_ENDPOINT` | GPT on Azure |
| Azure + Claude | `azure_openai` | `LLM_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `LLM_MODEL` | Claude on Azure (same provider!) |
| Azure AI Foundry | `azure_foundry` | `LLM_API_KEY`, `LLM_BASE_URL` | Claude via Azure AI Foundry; uses AnthropicFoundry SDK |
| AWS Bedrock (native) | `bedrock` | `AWS_REGION` + IAM creds | No API key needed |
| AWS Bedrock (proxy) | `bedrock_openai` | `LLM_API_KEY`, `LLM_BASE_URL` | OpenAI-compatible proxy |
| Local (Ollama) | `ollama` | (none) | Free, offline |
| Custom endpoint | `custom` | `LLM_API_KEY`, `LLM_BASE_URL` | Any OpenAI-compatible API |

`AZURE_OPENAI_DEPLOYMENT` is optional -- defaults to the model name if not set.

The Claude Code CLI mode (`main_cc.py`) uses the `claude` CLI on PATH and needs no `.env` configuration.

---

## Security Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SSL_VERIFY` | `true` | Set to `false` to disable SSL certificate verification (for internal networks with self-signed certs) |
| `STEALTH_BROWSER_ENABLED` | `true` | Set to `false` to disable CloakBrowser stealth scraping |

---

## Distributor API Configuration (Optional)

The agent queries distributor APIs for structured part data before falling back to web scraping. When an API returns 3+ attributes, LLM extraction is skipped entirely.

**Priority:** DigiKey -> Mouser -> McMaster -> Stealth Browser -> DuckDuckGo -> Stealth Fallback

```env
# DigiKey (free, OAuth2: developer.digikey.com)
DIGIKEY_CLIENT_ID=your_client_id
DIGIKEY_CLIENT_SECRET=your_client_secret

# Mouser (free, API key: api.mouser.com)
MOUSER_API_KEY=your_api_key

# McMaster-Carr (mTLS, email eprocurement@mcmaster.com)
MCMASTER_BEARER_TOKEN=your_token
MCMASTER_CLIENT_CERT=path/to/client.pem
MCMASTER_CLIENT_KEY=path/to/client-key.pem
```

---

## Optimization Features

| Feature | Description | Savings |
|---------|-------------|---------|
| **Batch classification** | 100 parts per CLI call (CC mode), 50 per API call | 75x faster than individual |
| **Deterministic classification** | Pattern matching from web content, 95% accuracy | 100% token savings for matched parts |
| **Regex pre-extraction** | Tables + key-value patterns before LLM | Smaller LLM extraction prompts |
| **Hybrid extraction prompt** | Priority schema hints + maximize coverage | Higher attribute yield |
| **LLM response cache** | 90-day classify / 30-day extract TTL | 100% for cached parts |
| **URL cache** | 30-day TTL + bad-entry eviction, shared across modes | Skips search entirely |
| **Content cleaner** | HTML table extraction + smart truncation | Better spec-to-noise ratio |
| **Manufacturer rotation** | Round-robin interleave by manufacturer | Reduces bot detection |
| **Distributor APIs** | DigiKey OAuth2, Mouser API, McMaster mTLS | 100% for API-matched parts |

---

## Adaptive Search

The agent finds sources dynamically based on part number presence in content -- no dependency on hardcoded domain lists.

- **Part number as PRIMARY signal:** Part number presence in page content is the primary scoring signal (+10 points). PREFERRED_DOMAINS is just a +2 tiebreaker, not a requirement.
- **Dynamic source discovery:** For each part, DuckDuckGo results are scored by whether the manufacturer part number actually appears in the page content. The best page wins regardless of domain.
- **No hardcoded domains:** Works for any manufacturer at scale (30K+ parts) without maintaining a list of "trusted" sites. New distributors and niche suppliers are discovered automatically.
- **Part number verification:** Pages are ranked by a `_spec_score()` function that checks for the presence of the searched part number, specification tables, and technical content. A page that contains the exact part number scores higher than a generic catalog page.
- **Datasheet search:** For electronic components, a dedicated datasheet search query is added to improve coverage.
- **URL cache as learned knowledge:** Once a good source is found for a manufacturer part number, it is cached for 30 days. Subsequent runs skip search entirely for cached parts, and bad entries are evicted automatically.

This approach scales to any industry vertical -- fasteners, bearings, electronics, semiconductor equipment -- without per-domain configuration.

---

## Claude Code CLI Features (Large Batches)

| Feature | Description |
|---|---|
| **Zero API keys** | Uses `claude` CLI (any backend: Anthropic, Azure, etc.) |
| **Batch classification** | 100 parts per CLI call (75x faster) |
| **Parallel workers** | N concurrent search+extract workers (default 4) |
| **Resume capability** | Saves progress after each part; re-run to resume |
| **Per-part error isolation** | One failed part doesn't stop the batch |
| **Periodic Excel writes** | Output files updated every 50 parts |
| **URL cache** | Reuses previously found URLs across runs |
| **Ctrl+C safe** | Saves progress and writes partial output on interrupt |

---

## Benchmark Results (44 parts)

| Configuration | Coverage | Avg Attrs/Part | Notes |
|--------------|----------|----------------|-------|
| Groq V8 | 86% | 14.1 | 5x improvement over baseline |
| Opus V8c (warm cache) | 93% | 5.7 | 39% improvement |

Coverage improves with each run due to URL cache warming and bad-entry eviction.

---

## Output Format

Each output Excel contains:
- All original input columns
- `Part Class` -- the classified category
- `TC Class ID` -- Teamcenter classification identifier
- `Source URL` -- the web page or API the attributes came from
- Extracted attribute columns specific to that class (canonical names, schema-ordered)
- 6 quality metric columns (color-coded: green >=80%, amber 50-79%, red <50%):
  - `Extraction Coverage %` -- TC schema attrs matched / total
  - `Source Reliability %` -- weighted source quality score
  - `Classification Confidence %` -- weighted classification confidence
  - `Source Type` -- API / Stealth / Web / Part Name
  - `LOV Compliance %` -- LOV-governed attrs with valid values
  - `Validation Action` -- Confirmed / Reclassified / Abstained

```
output/
  Flat Washer.xlsx
  Split Lock Washer.xlsx
  Deep Groove Ball Bearing.xlsx
  Tube Fitting.xlsx
  run_summary.html          # Dark-themed HTML executive summary
```

`output/run_summary.html` -- dark-themed HTML executive summary with KPIs, per-class breakdown, confidence distribution, low-confidence parts, and run details (including total tokens and avg tokens/part).

---

## Reliability Features

- **Multi-tier search:** APIs -> stealth browser -> cache -> DuckDuckGo -> fallback (7 tiers)
- **Deterministic classification:** 90+ class aliases with specificity resolution, 95% accuracy
- **Regex + LLM agreement tracking:** measures extraction confidence
- **Hybrid extraction prompt:** priority schema hints + maximize coverage
- **Canonical normalization:** 500+ alias mappings ensure consistent columns
- **JSON-based schema:** 93 classes, 46 attrs in `Classes.json` + `Attributes.json` with Teamcenter-compatible IDs, attribute inheritance, and LOV normalization
- **Unit handling:** inches, mm, or as-is (preserves original units)
- **Class-blind validation:** attribute-fit scoring against CLASS_SCHEMAS, dynamically computed universal attrs, abstain mechanism
- **Retry logic:** exponential backoff for timeouts, rate limits (429, 503)
- **Validation retry:** re-extraction for missing attrs when >50% schema attrs unfilled
- **Fallback to part name:** mines dimensions from part name when no web content found
- **CloakBrowser:** 33 C++ patches, bypasses Cloudflare/reCAPTCHA/FingerprintJS/Turnstile
- **Token tracking:** accumulated prompt + completion tokens from OpenAI and Anthropic API responses
- **Metrics tracking:** quality, cache effectiveness, regex/LLM agreement per run
- **Resume capability:** checkpoint after each part via progress.json
- **Windows UTF-8 encoding fix:** prevents encoding errors in output

---

## Supported Part Classes (93)

**Fasteners:** Flat Washer, Fender Washer, Split Lock Washer, Lock Washer, Internal Tooth Lock Washer, External Tooth Lock Washer, Hex Nut, Lock Nut, Wing Nut, Hex Bolt, Carriage Bolt, Cap Screw, Set Screw, Machine Screw, Socket Head Cap Screw, Cotter Pin, Dowel Pin, Roll Pin, Blind Rivet, E-Clip, C-Clip, Retaining Ring, Stud, Insert, Anchor

**Bearings & Motion:** Deep Groove Ball Bearing, Angular Contact Bearing, Needle Bearing, Crossed Roller Bearing, Linear Guide, Linear Block, Ball Screw

**Seals & Fittings:** O-Ring, Seal, Gasket, Tube Fitting, VCR Fitting, Pipe Fitting

**Pneumatics & Hydraulics:** Solenoid Valve, Pneumatic Valve, Pneumatic Cylinder, Flow Controller, Pressure Regulator

**Sensors & Electrical:** Proximity Sensor, Photoelectric Sensor, Fiber Optic Sensor, Laser Sensor, Pressure Sensor, Connector, Terminal, Relay, Timer

**Vacuum & Semiconductor:** Vacuum Valve, Gate Valve, Mass Flow Controller, Wafer Shipper, Wafer Carrier, Gas Filter, Liquid Filter, Pressure Gauge, Vacuum Gauge

Other part types are handled with a default attribute schema. To add a new class, add it to `schema/Classes.json` and regenerate with `python generate_schema.py`.

---

## Project Structure

```
PartClassifier/
├── main.py                    # API key CLI entry point
├── main_cc.py                 # Claude Code CLI entry point (zero API keys)
├── app.py                     # Streamlit web UI
├── plmxml_to_json.py          # PLMXML → JSON converter (Teamcenter export → Classes/Attributes JSON)
├── generate_schema.py         # Auto-generate aliases.json + classification_hints.json
├── requirements.txt           # Python dependencies
├── .env.example               # Configuration template (9 providers)
├── url_cache.json             # URL cache (30-day TTL, shared)
├── llm_cache.json             # LLM response cache (90/30-day TTL)
├── metrics_history.json       # Run metrics history
├── input/
│   └── PartClassifierInput.xlsx       # Sample input
├── schema/
│   ├── Classes.json                   # JSON schema: 93 classes, hierarchical tree, Teamcenter classids
│   ├── Attributes.json                # JSON schema: 46 attributes, numeric IDs, LOV values, ranges
│   ├── aliases.json                   # Auto-generated alias mappings (attribute + class aliases)
│   └── classification_hints.json      # Part-name keyword → class mappings for validation
├── output/                    # One .xlsx per part class (with TC Class ID)
├── docs/                      # HTML documentation suite
└── src/
    ├── llm_client.py          # Unified async LLM client (9 providers)
    ├── claude_code_client.py  # Claude CLI wrapper (batch + parallel)
    ├── part_classifier.py     # LLM classification + batch (100/call)
    ├── class_validator.py     # Class-blind extraction + attribute-fit validation
    ├── web_scraper.py         # 7-tier content lookup with URL caching
    ├── stealth_scraper.py     # CloakBrowser integration
    ├── api_sources.py         # DigiKey (OAuth2) / Mouser (API) / McMaster (mTLS)
    ├── attribute_extractor.py # Hybrid extraction + unit conversion + retry
    ├── class_extractor.py     # Deterministic classification (95% accuracy)
    ├── content_cleaner.py     # HTML table extraction + smart truncation
    ├── regex_extractor.py     # Pattern pre-extraction + agreement tracking
    ├── attr_schema.py         # JSON schema loader (93 classes, aliases, LOV normalization)
    ├── llm_cache.py           # Thread-safe LLM response cache with TTL
    ├── confidence.py          # Per-part quality metrics (6 functions)
    ├── report_generator.py    # HTML executive summary generator
    ├── metrics.py             # Run metrics tracker + history
    ├── shared.py              # Manufacturer rotation, cache I/O, atomic writes
    └── excel_handler.py       # Input reader + per-class writer + TC Class ID
```

---

## Notes

- The `url_cache.json` file is safe to commit -- it only contains public product URLs. Coverage improves with each run.
- The `llm_cache.json` file contains LLM responses and should not be committed.
- The `output/` folder is git-ignored and regenerated on each run.
- Progress files (`progress.json`, `progress_cc.json`) are auto-generated for resume support and deleted on completion.
- **Claude Code CLI mode** only needs `openpyxl` and `httpx` (+ `claude` CLI on PATH).
- **Fuzzy column matching:** Input Excel headers are matched fuzzily, so minor naming variations are handled automatically.
- Backward compatibility: `.env` files with only `GROQ_API_KEY` continue to work.
- Windows UTF-8 encoding fix applied globally at startup to prevent encoding errors.
