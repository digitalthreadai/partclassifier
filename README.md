# Part Classification Agent

An AI-powered agent that reads a list of mechanical parts from an Excel file, searches distributor APIs and the web for specifications, classifies each part by type, extracts structured attributes, and writes one Excel output file per part class -- ready for Teamcenter classification import.

**Three execution modes:**

| Mode | Entry point | LLM access | Best for |
|---|---|---|---|
| **API Key CLI** | `main.py` | Groq / OpenAI / Anthropic / Azure / Bedrock / Ollama | Direct API key users |
| **Claude Code CLI** | `main_cc.py` | `claude` CLI (zero API keys) | Enterprise, large batches (1K-20K+) |
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

No `.env` file or API keys needed.

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
2. Search: Distributor APIs -> Stealth Browser -> URL Cache -> DuckDuckGo -> Fallback
       |
3. Classify: Deterministic from web content -> LLM cache -> LLM
       |
4. Pre-extract: Regex patterns from tables, key-value pairs, standards, materials
       |
5. LLM validates pre-extracted values + fills gaps (temperature=0, deterministic)
       |
6. Write per-class Excel output files with canonical column names
```

For each part in the input Excel:

1. **Searches** for specs via distributor APIs first (DigiKey, Mouser, McMaster-Carr), falling back to CloakBrowser stealth scraping, then DuckDuckGo web search with curl_cffi.
2. **Classifies** the part deterministically from web content (breadcrumbs, category labels, URL paths). Falls back to LLM classification only when pattern matching is inconclusive. 60+ part classes supported.
3. **Pre-extracts** attributes via regex patterns from HTML tables, key-value patterns, standards (DIN/ASME/ISO), and materials.
4. **Validates** pre-extracted values with LLM and fills any gaps. Converts all dimensional values to the target unit (inches or mm).
5. **Writes** one output Excel file per part class into the `output/` folder, with consistent canonical column headers.

---

## Setup

### 1. Prerequisites

- **Python 3.11+** ([python.org](https://www.python.org/downloads/))
- **For API Key mode:** An API key from one of the supported LLM providers
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

See [SITECONFIGURATIONS.md](SITECONFIGURATIONS.md) for all 7 provider configurations.

### 4. Prepare input Excel

Place your file at `input/PartClassifierInput.xlsx` with columns: Part Number, Part Name, Manufacturer Part Number, Manufacturer Name, Unit of Measure.

### 5. Run

```bash
streamlit run app.py             # Web UI
python main.py                   # API key CLI
python main_cc.py                # Claude Code CLI (no API keys)
python main_cc.py --workers 8    # Claude Code CLI with 8 parallel workers
```

---

## LLM Configuration

7 providers supported:

| Provider | Default Model | Key Required | Get Key |
|----------|--------------|-------------|---------|
| `groq` | llama-3.3-70b-versatile | Yes (free) | console.groq.com |
| `openai` | gpt-4o | Yes | platform.openai.com |
| `anthropic` | claude-sonnet-4-20250514 | Yes | console.anthropic.com |
| `azure_openai` | gpt-4o | Yes | portal.azure.com |
| `bedrock` | anthropic.claude-sonnet-4-20250514-v1:0 | No (AWS creds) | console.aws.amazon.com |
| `ollama` | llama3.1 | No | ollama.ai |
| `custom` | (user-defined) | Varies | Your endpoint |

---

## Distributor API Configuration (Optional)

The agent queries distributor APIs for structured part data before falling back to web scraping. When an API returns 3+ attributes, LLM extraction is skipped entirely.

**Priority:** DigiKey -> Mouser -> McMaster -> Stealth Browser -> DuckDuckGo -> Stealth Fallback

```env
# DigiKey (free: developer.digikey.com)
DIGIKEY_CLIENT_ID=your_client_id
DIGIKEY_CLIENT_SECRET=your_client_secret

# Mouser (free: api.mouser.com)
MOUSER_API_KEY=your_api_key

# McMaster-Carr (email eprocurement@mcmaster.com)
MCMASTER_BEARER_TOKEN=your_token
```

---

## Optimization Features

| Feature | Description | Savings |
|---------|-------------|---------|
| **Batch classification** | 50 parts per LLM call | ~95% fewer classify tokens |
| **Deterministic classification** | Pattern matching from web content, no LLM needed | 100% for matched parts |
| **Regex pre-extraction** | Tables + key-value patterns before LLM | Smaller LLM extraction prompts |
| **LLM response cache** | 90-day classify / 30-day extract TTL | 100% for cached parts |
| **URL cache** | 30-day TTL, shared across modes | Skips search entirely |
| **Manufacturer rotation** | Round-robin interleave by manufacturer | Reduces bot detection |
| **Distributor APIs** | Structured data, bypasses LLM extraction | 100% for API-matched parts |

---

## Claude Code CLI Features (Large Batches)

| Feature | Description |
|---|---|
| **Zero API keys** | Uses `claude` CLI (any backend: Anthropic, Azure, etc.) |
| **Batch classification** | 100 parts per CLI call |
| **Parallel workers** | N concurrent search+extract workers (default 4) |
| **Resume capability** | Saves progress after each part; re-run to resume |
| **Per-part error isolation** | One failed part doesn't stop the batch |
| **Periodic Excel writes** | Output files updated every 50 parts |
| **URL cache** | Reuses previously found URLs across runs |
| **Ctrl+C safe** | Saves progress and writes partial output on interrupt |

---

## Output Format

Each output Excel contains:
- All original input columns
- `Part Class` -- the classified category
- `Source URL` -- the web page or API the attributes came from
- Extracted attribute columns specific to that class (canonical names, ordered per schema)

---

## Reliability Features

- **Multi-tier search:** APIs -> stealth browser -> cache -> DuckDuckGo -> fallback
- **Deterministic classification:** 90+ class aliases with specificity resolution
- **Regex + LLM agreement tracking:** measures extraction confidence
- **Canonical normalization:** 500+ alias mappings ensure consistent columns
- **Unit conversion:** inches <-> mm per part's specified unit
- **Retry logic:** exponential backoff for timeouts, rate limits (429, 503)
- **Fallback to part name:** mines dimensions from part name when no web content found
- **CloakBrowser:** 33 C++ patches, bypasses Cloudflare/reCAPTCHA/FingerprintJS
- **Metrics tracking:** quality, cache effectiveness, regex/LLM agreement per run

---

## Supported Part Classes (60+)

**Fasteners:** Flat Washer, Fender Washer, Split Lock Washer, Lock Washer, Internal Tooth Lock Washer, External Tooth Lock Washer, Hex Nut, Lock Nut, Wing Nut, Hex Bolt, Carriage Bolt, Cap Screw, Set Screw, Machine Screw, Socket Head Cap Screw, Cotter Pin, Dowel Pin, Roll Pin, Blind Rivet, E-Clip, C-Clip, Retaining Ring, Stud, Insert, Anchor

**Bearings & Motion:** Deep Groove Ball Bearing, Angular Contact Bearing, Needle Bearing, Crossed Roller Bearing, Linear Guide, Linear Block, Ball Screw

**Seals & Fittings:** O-Ring, Seal, Gasket, Tube Fitting, VCR Fitting, Pipe Fitting

**Pneumatics & Hydraulics:** Solenoid Valve, Pneumatic Valve, Pneumatic Cylinder, Flow Controller, Pressure Regulator

**Sensors & Electrical:** Proximity Sensor, Photoelectric Sensor, Fiber Optic Sensor, Laser Sensor, Pressure Sensor, Connector, Terminal, Relay, Timer

**Vacuum & Semiconductor:** Vacuum Valve, Gate Valve, Mass Flow Controller, Wafer Shipper, Wafer Carrier, Gas Filter, Liquid Filter, Pressure Gauge, Vacuum Gauge

Other part types are handled with a default attribute schema. To add a new class, add its canonical attribute list to `CLASS_SCHEMAS` in `src/attr_schema.py`.

---

## Project Structure

```
PartClassifier/
├── main.py                    # API key CLI entry point
├── main_cc.py                 # Claude Code CLI entry point (zero API keys)
├── app.py                     # Streamlit web UI
├── requirements.txt           # Python dependencies
├── .env.example               # Configuration template (7 providers)
├── url_cache.json             # URL cache (30-day TTL, shared)
├── llm_cache.json             # LLM response cache (90/30-day TTL)
├── metrics_history.json       # Run metrics history
├── input/
│   └── PartClassifierInput.xlsx
├── output/                    # One .xlsx per part class
└── src/
    ├── llm_client.py          # Unified async LLM client (7 providers)
    ├── claude_code_client.py  # Claude CLI wrapper
    ├── part_classifier.py     # LLM classification + batch (50/call)
    ├── web_scraper.py         # Multi-tier content lookup
    ├── stealth_scraper.py     # CloakBrowser integration
    ├── api_sources.py         # DigiKey/Mouser/McMaster APIs
    ├── attribute_extractor.py # LLM extraction + unit conversion
    ├── class_extractor.py     # Deterministic class from web content
    ├── content_cleaner.py     # HTML table extraction
    ├── regex_extractor.py     # Pattern pre-extraction + agreement
    ├── attr_schema.py         # 60+ classes, 500+ aliases
    ├── llm_cache.py           # LLM response cache
    ├── metrics.py             # Run metrics tracker
    ├── shared.py              # Manufacturer rotation, cache I/O
    └── excel_handler.py       # Excel read/write
```

---

## Notes

- The `url_cache.json` file is safe to commit -- it only contains public product URLs.
- The `llm_cache.json` file contains LLM responses and should not be committed.
- The `output/` folder is git-ignored and regenerated on each run.
- Progress files (`progress.json`, `progress_cc.json`) are auto-generated for resume support and deleted on completion.
- **Claude Code CLI mode** only needs `openpyxl` and `httpx` (+ `claude` CLI on PATH).
- Backward compatibility: `.env` files with only `GROQ_API_KEY` continue to work.
