# Part Classification Agent

A production-grade AI agent that reads mechanical parts from Excel, searches distributor APIs and the web for specifications, classifies each part into 81 categories, extracts structured attributes via regex pre-extraction + LLM validation, and writes per-class Excel output files with TC Class ID -- ready for Teamcenter PLM import.

**7,031 LOC | 17 modules | 8 LLM providers | 3 distributor APIs | 81 part classes | 46 attributes | 500+ aliases**

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
```

---

## Pipeline (6 Steps)

```
1. Read Excel input (Part Number, Mfg Part Number, Mfg Name, Unit)
       |
2. Multi-tier search: APIs -> Stealth Browser -> URL Cache -> DuckDuckGo -> Fallback
       |
3. Classify: Deterministic from web content (95% accuracy) -> LLM cache -> LLM
       |
4. Pre-extract: Regex patterns from tables, key-value pairs, standards, materials
       |
5. LLM validates pre-extracted values + fills gaps (hybrid prompt, temperature=0)
       |
6. Write per-class Excel output with TC Class ID and canonical column names
```

For each part in the input Excel:

1. **Searches** for specs via distributor APIs first (DigiKey OAuth2, Mouser API key, McMaster-Carr mTLS), falling back to CloakBrowser stealth scraping, then DuckDuckGo web search with curl_cffi (Chrome 124 TLS fingerprint).
2. **Cleans** content via HTML table extraction and smart truncation (3K/5K/8K char limits) to prioritize specs over navigation boilerplate.
3. **Classifies** the part deterministically from web content (breadcrumbs, category labels, URL paths) with 95% accuracy. Falls back to LLM classification only when inconclusive. 81 part classes supported.
4. **Pre-extracts** attributes via regex patterns from HTML tables, key-value patterns, standards (DIN/ASME/ISO), and materials.
5. **Validates** pre-extracted values with LLM using hybrid prompts (priority schema hints + maximize coverage) and fills any gaps. Converts all dimensional values to the target unit (inches or mm).
6. **Normalizes** attributes via 500+ alias mappings to canonical names and **writes** one output Excel file per part class into the `output/` folder, with TC Class ID and schema-ordered columns.

---

## Setup

### 1. Prerequisites

- **Python 3.11+** ([python.org](https://www.python.org/downloads/))
- **For API Key mode:** An API key from one of the 8 supported LLM providers
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

See [SITECONFIGURATIONS.md](SITECONFIGURATIONS.md) for all 8 provider configurations.

### 4. Prepare input Excel

Place your file at `input/PartClassifierInput.xlsx` with columns: Part Number, Part Name, Manufacturer Part Number, Manufacturer Name, Unit of Measure.

### 5. Classification Schema (optional customization)

The Excel-based schema (`input/ClassificationSchema.xlsx`) defines 81 part classes, 46 canonical attributes, and 169 alias mappings. Edit this file to add new classes or modify attribute definitions. Falls back to hardcoded schemas if missing.

### 6. Run

```bash
streamlit run app.py             # Web UI
python main.py                   # API key CLI
python main_cc.py                # Claude Code CLI (no API keys)
python main_cc.py --workers 8    # Claude Code CLI with 8 parallel workers
```

---

## LLM Configuration

8 providers supported:

| Provider | Default Model | Key Required | Get Key |
|----------|--------------|-------------|---------|
| `groq` | llama-3.3-70b-versatile | Yes (free) | console.groq.com |
| `openai` | gpt-4o | Yes | platform.openai.com |
| `anthropic` | claude-sonnet-4-20250514 | Yes | console.anthropic.com |
| `azure_openai` | gpt-4o | Yes | portal.azure.com |
| `bedrock` | anthropic.claude-sonnet-4-20250514-v1:0 | No (AWS creds) | console.aws.amazon.com |
| `ollama` | llama3.1 | No | ollama.ai |
| `custom` | (user-defined) | Varies | Your endpoint |
| Claude Code CLI | (any backend) | No | claude CLI on PATH |

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

```
output/
  Flat Washer.xlsx
  Split Lock Washer.xlsx
  Deep Groove Ball Bearing.xlsx
  Tube Fitting.xlsx
```

---

## Reliability Features

- **Multi-tier search:** APIs -> stealth browser -> cache -> DuckDuckGo -> fallback (7 tiers)
- **Deterministic classification:** 90+ class aliases with specificity resolution, 95% accuracy
- **Regex + LLM agreement tracking:** measures extraction confidence
- **Hybrid extraction prompt:** priority schema hints + maximize coverage
- **Canonical normalization:** 500+ alias mappings ensure consistent columns
- **Excel-based schema:** 81 classes, 46 attrs, 169 aliases in `ClassificationSchema.xlsx`
- **Unit conversion:** inches <-> mm per part's specified unit
- **Retry logic:** exponential backoff for timeouts, rate limits (429, 503)
- **Validation retry:** re-extraction for missing attrs when >50% schema attrs unfilled
- **Fallback to part name:** mines dimensions from part name when no web content found
- **CloakBrowser:** 33 C++ patches, bypasses Cloudflare/reCAPTCHA/FingerprintJS/Turnstile
- **Metrics tracking:** quality, cache effectiveness, regex/LLM agreement per run
- **Resume capability:** checkpoint after each part via progress.json
- **Windows UTF-8 encoding fix:** prevents encoding errors in output
- **21 production-ready bug fixes:** comprehensive edge case handling

---

## Supported Part Classes (81)

**Fasteners:** Flat Washer, Fender Washer, Split Lock Washer, Lock Washer, Internal Tooth Lock Washer, External Tooth Lock Washer, Hex Nut, Lock Nut, Wing Nut, Hex Bolt, Carriage Bolt, Cap Screw, Set Screw, Machine Screw, Socket Head Cap Screw, Cotter Pin, Dowel Pin, Roll Pin, Blind Rivet, E-Clip, C-Clip, Retaining Ring, Stud, Insert, Anchor

**Bearings & Motion:** Deep Groove Ball Bearing, Angular Contact Bearing, Needle Bearing, Crossed Roller Bearing, Linear Guide, Linear Block, Ball Screw

**Seals & Fittings:** O-Ring, Seal, Gasket, Tube Fitting, VCR Fitting, Pipe Fitting

**Pneumatics & Hydraulics:** Solenoid Valve, Pneumatic Valve, Pneumatic Cylinder, Flow Controller, Pressure Regulator

**Sensors & Electrical:** Proximity Sensor, Photoelectric Sensor, Fiber Optic Sensor, Laser Sensor, Pressure Sensor, Connector, Terminal, Relay, Timer

**Vacuum & Semiconductor:** Vacuum Valve, Gate Valve, Mass Flow Controller, Wafer Shipper, Wafer Carrier, Gas Filter, Liquid Filter, Pressure Gauge, Vacuum Gauge

Other part types are handled with a default attribute schema. To add a new class, add it to `input/ClassificationSchema.xlsx` or `CLASS_SCHEMAS` in `src/attr_schema.py`.

---

## Project Structure

```
PartClassifier/
├── main.py                    # API key CLI entry point
├── main_cc.py                 # Claude Code CLI entry point (zero API keys)
├── app.py                     # Streamlit web UI
├── requirements.txt           # Python dependencies
├── .env.example               # Configuration template (8 providers)
├── url_cache.json             # URL cache (30-day TTL, shared)
├── llm_cache.json             # LLM response cache (90/30-day TTL)
├── metrics_history.json       # Run metrics history
├── input/
│   ├── PartClassifierInput.xlsx       # Sample input
│   └── ClassificationSchema.xlsx      # Excel-based schema (81 classes, 46 attrs, 169 aliases)
├── output/                    # One .xlsx per part class (with TC Class ID)
├── docs/                      # HTML documentation suite
└── src/
    ├── llm_client.py          # Unified async LLM client (8 providers)
    ├── claude_code_client.py  # Claude CLI wrapper (batch + parallel)
    ├── part_classifier.py     # LLM classification + batch (100/call)
    ├── web_scraper.py         # 7-tier content lookup with URL caching
    ├── stealth_scraper.py     # CloakBrowser integration
    ├── api_sources.py         # DigiKey (OAuth2) / Mouser (API) / McMaster (mTLS)
    ├── attribute_extractor.py # Hybrid extraction + unit conversion + retry
    ├── class_extractor.py     # Deterministic classification (95% accuracy)
    ├── content_cleaner.py     # HTML table extraction + smart truncation
    ├── regex_extractor.py     # Pattern pre-extraction + agreement tracking
    ├── attr_schema.py         # Excel-based schema loader (81 classes, 500+ aliases)
    ├── llm_cache.py           # Thread-safe LLM response cache with TTL
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
- Backward compatibility: `.env` files with only `GROQ_API_KEY` continue to work.
- Windows UTF-8 encoding fix applied globally at startup to prevent encoding errors.
