# Part Classification Agent

A production-grade AI agent that reads mechanical parts from Excel, searches distributor APIs and the web for specifications, classifies each part into 93 categories using a classify-then-blind-extract-then-validate-then-extract architecture, and writes per-class Excel output files with TC Class ID -- ready for Teamcenter PLM import. Includes a PLMXML-to-JSON converter for importing Teamcenter classification hierarchies.

**~8,400 LOC | 20 modules | 9 LLM providers | 3 distributor APIs | 93 part classes | 46 attributes | 500+ aliases | class_validator.py | classification_hints.json | configurable aliases.json**

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
1. Read Excel input (+ infer UOM from part name if not provided)
       |
2. Multi-tier search (APIs -> Stealth -> Cache -> DuckDuckGo)
       |
   2b. Part name signal validation → evict cache + re-search if page mismatches
       |
3. Initial classify (part name signals -> web content patterns -> LLM fallback)
       |
4. Class-blind LLM extraction (no class bias -- extracts ALL specs)
       |
5. Validate classification (attribute-fit scoring against CLASS_SCHEMAS)
       |
6. Class-aware LLM extraction (with validated class + regex pre-extraction)
       |
7. Normalize attrs (fractions → decimal, strip UOM suffix, LOV normalization)
       |
8. Write per-class Excel output with TC Class ID + HTML executive summary
```

For each part in the input Excel:

1. **Reads** input, inferring UOM from the part name if the Unit of Measure column is blank (e.g., "M10" → metric, `"` marks → inches; abstains on conflicts).
2. **Searches** for specs via distributor APIs first (DigiKey OAuth2, Mouser API key, McMaster-Carr mTLS), falling back to CloakBrowser stealth scraping, then DuckDuckGo web search with curl_cffi (Chrome 124 TLS fingerprint).
   - **Part name signal validation:** Dimensional signals (e.g., `.136ID`, `.280OD`, `M8 x 1.25`) are parsed from the part name and matched against the scraped page. If the page doesn't contain the expected values, the URL cache entry is evicted and the search retries once.
3. **Classifies** — part name signals (thread sizes, dimensions) are the highest-priority signal. Falls back to deterministic web content classification (breadcrumbs, category labels, URL paths), then LLM. 93 part classes supported.
4. **Class-blind LLM extraction** extracts ALL specs without class bias, breaking the circular dependency between classification and extraction.
5. **Validates** classification via attribute-fit scoring against CLASS_SCHEMAS. Dynamically computes universal attrs (>90% of classes). Reclassifies only with strong evidence (MIN_ADVANTAGE=2). Abstains when uncertain.
6. **Class-aware extraction** with validated class + regex pre-extraction + unit handling. Supports inches, mm, or as-is mode (preserves original units when not specified). PDF spec files use native text extraction with LLM vision OCR fallback for scanned documents.
7. **Normalizes** attributes: fraction values converted to decimal ("13/64\"" → "0.203\"), unit suffixes stripped from numeric values ("0.23 inches" → "0.23"), LOV values resolved via RapidFuzz string matching then LLM semantic fallback if needed, ranges averaged (original value preserved in a companion column).
8. **Writes** one output Excel file per part class into the `output/` folder, with TC Class ID and schema-ordered columns. Also generates an HTML executive summary report (`output/run_summary.html`).

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

## Processing Options

| Variable | Default | Description |
|----------|---------|-------------|
| `POST_PROCESS_DEDUP` | `false` | Set to `true` to enable post-processing deduplication of agent-extracted columns. Per-part Phase A removes an agent column when it exactly matches a TC schema value for the same part. Phase B merges two agent columns when they match each other on the same part and an LLM confirms semantic equivalence. All deduplication is confined to the same part row — no cross-part merging. Pre/post Excel files written side-by-side for comparison. Adds latency; useful for large batches with overlapping agent-extracted attrs. |

---

## Attribute Type Metadata

Each attribute in `schema/Attributes.json` now carries six additional fields that drive type-aware normalization:

| Field | Values | Description |
|-------|--------|-------------|
| `type` | `float`, `integer`, `string`, `lov` | Teamcenter datatype for this attribute |
| `unit` | `mm`, `in`, `deg`, etc. | Expected unit of measure |
| `length` | integer | Max character count (strings) or max digits (numeric) |
| `precision` | integer | Decimal places to round to (float only) |
| `case` | `0`, `1` | LOV case sensitivity: 0 = case-insensitive, 1 = case-sensitive |
| `sign` | `0`, `1` | Sign constraint: 0 = positive only, 1 = negative only |

### attr_type_rules.json

`schema/attr_type_rules.json` configures which normalization operations apply to each Python type. Each type entry lists the operations that are enabled for it:

```json
{
  "type_behaviors": {
    "float":   ["fraction_to_decimal", "average_range", "strip_unit", "apply_precision", "apply_sign"],
    "integer": ["fraction_to_decimal", "average_range", "strip_unit", "apply_sign"],
    "string":  ["apply_length"],
    "lov":     ["strip_unit", "lov_match", "apply_length"]
  }
}
```

To add a new type, append an entry to `type_behaviors` with the list of operations that should apply.

### CLASS_ATTR_META

The `CLASS_ATTR_META` dictionary in `src/attr_schema.py` stores per-class type metadata, keyed by `(class_name, attr_name)`. It is populated directly from `Attributes.json` at schema load time. There is no global fallback — if an attribute is not defined in the schema for a class, normalization skips type-specific steps for that attribute.

### 7-Step Normalization Order

For each extracted attribute value, normalization runs in this order:

1. **fraction → decimal** — converts "13/64\"" to "0.203", "1-1/2\"" to "1.5"; date/version strings are guarded
2. **range average** — averages "3.8 to 4.2 mm" to "3.95", original preserved in companion column
3. **strip unit** — removes trailing UOM suffix from numeric values ("0.23 inches" → "0.23")
4. **apply_precision** — rounds float values to the attribute's declared decimal places (runs before LOV matching so the candidate is already normalized)
5. **LOV match** — RapidFuzz string match against class-scoped LOV; LLM semantic fallback if fuzzy match fails
6. **apply_length** — truncates to max character/digit length
7. **apply_sign** — rejects or flags values that violate the sign constraint

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
| **URL cache** | 30-day TTL + bad-entry eviction + signal validation | Skips search entirely; evicts bad URLs |
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
  - `Source Type` -- API / Stealth / Web / Part Name / Spec File (Text) / Spec File (Vision)
  - `LOV Compliance %` -- LOV-governed attrs with valid values
  - `Validation Action` -- Confirmed / Reclassified / Abstained
- **`<Attr>-Original-RANGE-Value` columns** (steel blue header) -- original range string before averaging (e.g., "3.8 to 4.2 mm" alongside averaged "3.95")
- **`<Attr>-Original-FRACTION-Value` columns** (amber header) -- original fraction before decimal conversion (e.g., "13/64\"" alongside "0.203")
- **`Unit of Measure (Agent)` column** (navy blue TC header) -- when the input UOM is blank, the agent infers the unit from extracted specs and writes it here; populated for all parts where UOM was auto-detected
- Agent-extracted columns (attrs found outside the TC schema, not class-scoped)

**LOV mismatch columns:** The `<Attr>-NotPresentInLOV` companion column records the post-conversion value (e.g., "0.25") rather than the pre-conversion raw string (e.g., "1/4 in"), so the value shown is what was actually tested against the LOV list.

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
- **Part name signal validation:** Dimensional signals parsed from the part name (thread sizes, ID/OD/thickness) are matched against scraped content; cache evicted + re-search triggered if page doesn't contain expected values (max 1 retry)
- **UOM inference:** Unit of Measure auto-detected from part name when not in input (M-series → metric, inch marks → imperial; abstains on conflict)
- **Deterministic classification:** Part name signals are highest priority; 90+ class aliases with specificity resolution, 95% accuracy
- **Regex + LLM agreement tracking:** measures extraction confidence
- **Hybrid extraction prompt:** priority schema hints + maximize coverage
- **Canonical normalization:** 500+ alias mappings ensure consistent columns
- **JSON-based schema:** 93 classes, 46 attrs in `Classes.json` + `Attributes.json` with Teamcenter-compatible IDs, attribute inheritance, and class-scoped LOV normalization (CLASS_LOV_MAP — strictly class-scoped, no global fallback; LOV compliance % always reflects the actual class LOV list)
- **LOV normalization:** RapidFuzz string matching → LLM semantic fallback (batched, validated against LOV list before acceptance)
- **Type-aware normalization:** precision rounding, sign validation, and length truncation applied per Teamcenter attribute datatype, driven by `schema/attr_type_rules.json` and per-class `CLASS_ATTR_META`
- **Fraction → decimal:** "13/64\"" → "0.203\"", "1-1/2\"" → "1.5\"", works inside ranges; date/version strings guarded
- **Unit suffix stripping:** Numeric attribute values strip trailing UOM ("0.23 inches" → "0.23"); datatype-aware to protect strings
- **Range original preservation:** Original range string retained in companion column when averaged
- **Unit handling:** inches, mm, or as-is (preserves original units)
- **PDF vision fallback:** Native text extraction (pdfplumber) with LLM vision OCR fallback for scanned/garbled PDFs; quality-scored selection
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
│   ├── Attributes.json                # JSON schema: 46 attributes, numeric IDs, LOV values, ranges, type metadata (type/unit/length/precision/case/sign)
│   ├── attr_type_rules.json           # Per-Python-type normalization operation list (fraction_to_decimal, average_range, strip_unit, apply_precision, lov_match, apply_length, apply_sign)
│   ├── aliases.json                   # Auto-generated alias mappings (attribute + class aliases)
│   └── classification_hints.json      # Part-name keyword → class mappings for validation
├── output/                    # One .xlsx per part class (with TC Class ID)
├── docs/                      # HTML documentation suite
└── src/
    ├── llm_client.py          # Unified async LLM client (9 providers, vision capability detection)
    ├── claude_code_client.py  # Claude CLI wrapper (batch + parallel)
    ├── part_classifier.py     # LLM classification + batch (100/call)
    ├── class_validator.py     # Class-blind extraction + attribute-fit validation
    ├── web_scraper.py         # 7-tier content lookup with URL caching
    ├── stealth_scraper.py     # CloakBrowser integration
    ├── api_sources.py         # DigiKey (OAuth2) / Mouser (API) / McMaster (mTLS)
    ├── attribute_extractor.py # Hybrid extraction + LOV LLM augmentation + unit conversion + retry
    ├── class_extractor.py     # Deterministic classification (95% accuracy)
    ├── content_cleaner.py     # HTML table extraction + smart truncation
    ├── regex_extractor.py     # Pattern pre-extraction + agreement tracking
    ├── attr_schema.py         # JSON schema loader (93 classes, aliases, class-scoped LOV normalization)
    ├── llm_cache.py           # Thread-safe LLM response cache with TTL
    ├── confidence.py          # Per-part quality metrics (6 functions)
    ├── report_generator.py    # HTML executive summary generator
    ├── metrics.py             # Run metrics tracker + history
    ├── shared.py              # Manufacturer rotation, cache I/O, atomic writes
    ├── excel_handler.py       # Input reader + per-class writer + TC Class ID + range/fraction orig cols
    ├── file_extractor.py      # PDF/spec file extraction (native text + LLM vision OCR fallback)
    ├── part_name_parser.py    # Part name signal parsing, UOM inference, web page validation
    ├── post_processor.py      # Agent column deduplication (transitive chains, LLM semantic confirmation)
    └── range_handler.py       # Range averaging, fraction→decimal conversion, unit suffix stripping
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
