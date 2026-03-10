# Part Classification Agent

An AI-powered agent that reads a list of mechanical parts from an Excel file, classifies each part by type, scrapes manufacturer/distributor websites for specifications, and writes one structured Excel output file per part class -- ready for Teamcenter classification import.

The agent can be used via a **Streamlit web UI** or directly from the **command line**.

---

## Quick Start

```bash
git clone https://github.com/digitalthreadai/partclassifier.git
cd partclassifier
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501, configure your LLM provider in the sidebar, select your input file, and click **Run Classification**.

---

## What It Does

For each part in the input Excel:

1. **Classifies** the part (Flat Washer, Split Lock Washer, Internal Tooth Lock Washer, Hex Bolt, etc.) using an LLM based on the Part Name.
2. **Searches** DuckDuckGo for the Manufacturer Part Number and scrapes the best product page found.
3. **Extracts** all relevant attributes (dimensions, material, finish, standard, compliance, etc.) using an LLM, converting values to the unit of measure specified per part (inches or mm).
4. **Writes** one output Excel file per part class into the `output/` folder, with consistent column headers across all parts of the same class.

---

## Agent Workflow

```
Input Excel
    |
    v
[ExcelHandler] --> reads Part Number, Part Name, Manufacturer Part Number,
                        Manufacturer Name, Unit of Measure
    |
    v
[PartClassifier] --> calls LLM (configurable provider + model)
                      classifies part name -> "Split Lock Washer", "Flat Washer", etc.
    |
    v
[WebScraper] --> checks url_cache.json for known-good URL
              --> if no cache: runs DuckDuckGo searches, scores all candidate pages
              --> scrapes best page using curl_cffi (real Chrome TLS fingerprint)
              --> caches the winning URL for future runs
    |
    v
[AttributeExtractor] --> sends scraped text + part class + unit to LLM
                      --> LLM extracts structured attributes using canonical names
                      --> converts all dimensional values to target unit (inches or mm)
                      --> normalizes attribute names via alias mapping
    |
    v
[ExcelHandler] --> groups results by part class
              --> writes one .xlsx per class with consistent column headers
```

If no web content is found, the extractor falls back to mining any dimensions encoded in the Part Name itself.

---

## Setup

### 1. Prerequisites

- **Python 3.11+** ([python.org](https://www.python.org/downloads/))
- An API key from one of the supported LLM providers (see below)
- **Git** (optional, for cloning the repo)

### 2. Clone the repository

```bash
git clone https://github.com/digitalthreadai/partclassifier.git
cd partclassifier
```

### 3. Create a virtual environment (recommended)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `openai` -- OpenAI-compatible SDK (used for Groq, OpenAI, Ollama, and custom providers)
- `anthropic` -- Anthropic SDK (only needed if using Claude models)
- `openpyxl` -- Excel read/write
- `curl_cffi` -- HTTP client with real Chrome TLS fingerprint
- `beautifulsoup4` -- HTML parsing
- `python-dotenv` -- loads `.env` file

### 5. Configure LLM provider

Copy the example env file:

```bash
cp .env.example .env
```

Edit `.env` with your chosen provider. See [LLM Configuration](#llm-configuration) below for all options.

**Quick start with Groq (free):**
```
LLM_PROVIDER=groq
LLM_API_KEY=your_groq_api_key_here
```

### 6. Prepare input Excel

Place your input file at:

```
input/PartClassifierInput.xlsx
```

Required columns (exact names):

| Column | Description |
|---|---|
| Part Number | Your internal part number |
| Part Name | Descriptive name (used for classification) |
| Manufacturer Part Number | Used for web search and scraping |
| Manufacturer Name | Manufacturer or distributor name |
| Unit of Measure | `inches` or `mm` -- all output values will use this unit |

A sample input file is included in the repo.

### 7. Run

**Option A: Web UI (recommended)**

```bash
streamlit run app.py
```

This opens a browser at http://localhost:8501 with:
- **Sidebar** -- select LLM provider, enter API key, choose model, and click Save (writes to `.env` automatically)
- **Main area** -- pick input folder and file, preview data, click **Run Classification**
- **Results** -- progress bar, per-part breakdown, and download buttons for output files

**Option B: Command line**

```bash
python main.py
```

Requires `.env` to be configured manually (see [LLM Configuration](#llm-configuration)).

Output files appear in the `output/` folder, one per part class:

```
output/
  Flat Washer.xlsx
  Split Lock Washer.xlsx
  Internal Tooth Lock Washer.xlsx
  ...
```

---

## LLM Configuration

The agent supports multiple LLM providers. Configure via three variables in `.env`:

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | Yes | `groq`, `openai`, `anthropic`, `ollama`, or `custom` |
| `LLM_API_KEY` | Yes* | API key for your provider (*not needed for Ollama) |
| `LLM_MODEL` | No | Override the default model for your provider |
| `LLM_BASE_URL` | No | Custom API endpoint (only for `custom` provider) |

### Provider Examples

**Groq (free, recommended for getting started)**
```env
LLM_PROVIDER=groq
LLM_API_KEY=gsk_your_groq_key_here
```
Default model: `llama-3.3-70b-versatile` | Get key: https://console.groq.com/keys

**OpenAI (GPT-4o, GPT-4-turbo)**
```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-your_openai_key_here
LLM_MODEL=gpt-4o
```
Default model: `gpt-4o` | Get key: https://platform.openai.com/api-keys

**Anthropic (Claude Opus, Sonnet, Haiku)**
```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-your_anthropic_key_here
LLM_MODEL=claude-sonnet-4-20250514
```
Default model: `claude-sonnet-4-20250514` | Get key: https://console.anthropic.com/settings/keys

Other Claude models: `claude-opus-4-20250514`, `claude-haiku-4-5-20251001`

**Ollama (local, free, no API key needed)**
```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
```
Default model: `llama3.1` | Install: https://ollama.ai

Make sure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull llama3.1`).

**Custom OpenAI-compatible API**
```env
LLM_PROVIDER=custom
LLM_API_KEY=your_key
LLM_BASE_URL=https://your-api-endpoint.com/v1
LLM_MODEL=your-model-name
```

### Backward Compatibility

If `LLM_PROVIDER` is not set, the agent falls back to reading `GROQ_API_KEY` and using Groq automatically. Existing `.env` files with only `GROQ_API_KEY` will continue to work.

---

## Output Format

Each output Excel contains:

- All original input columns
- `Part Class` -- the classified category
- `Source URL` -- the web page the attributes were extracted from
- All extracted attribute columns specific to that class

Attribute columns are ordered canonically per class (e.g., Screw Size, Inner Diameter, Outer Diameter, Thickness, Material, Finish, Hardness, Standard, ...).

---

## Reliability Features

### URL Caching (`url_cache.json`)
After the first successful scrape for a part number, the winning URL is saved to `url_cache.json`. On subsequent runs, the agent goes directly to that URL instead of re-searching -- making reruns fast and deterministic. To force a fresh search for a part, delete its entry from the cache.

### Preferred Source Domains
The agent prioritizes trusted industrial fastener distributor sites over generic results:
- `skdin.com`, `aftfasteners.com`, `boltdepot.com`, `fastenal.com`, `aspenfasteners.com`, `albanycountyfasteners.com`, `olander.com`, `zoro.com`

### Spec Scoring
Every candidate page is scored by the density of spec-related keywords (inner diameter, outer diameter, thickness, material, hardness, DIN, ASME, ISO, etc.) plus a bonus if the exact part number appears on the page. The highest-scoring page wins.

### Bot Detection Bypass
`curl_cffi` is used instead of `requests` for all HTTP calls. It impersonates a real Chrome browser at the TLS level (JA3/JA4 fingerprint), which bypasses basic bot detection that blocks Python's default HTTP stack.

### Canonical Attribute Normalization (`src/attr_schema.py`)
Different sources use different names for the same attribute ("Screw Size" vs "Thread Size" vs "For Screw Size"). The agent maps all known aliases to a single canonical name per class, ensuring all parts of the same class have identical Excel columns regardless of which source was used.

### Unit Conversion
The LLM is explicitly instructed to detect the unit system of the source content and convert all dimensional values to the unit specified in the input (`inches` or `mm`). This ensures consistent output even when the source page only provides one unit system.

### Fallback to Part Name
If no web content is found (source unavailable, rate-limited, etc.), the agent extracts whatever dimensions are encoded in the Part Name string itself (e.g., `WSHR, SPT LK, M20, 21.2 MM ID, 33.6 MM OD`).

### DuckDuckGo Rate Limit Mitigation
A 1.5-second delay is inserted between consecutive DuckDuckGo search queries to avoid triggering rate limits.

---

## Project Structure

```
PartClassifier/
├── app.py                     # Streamlit web UI
├── main.py                    # CLI entry point -- orchestrates the full pipeline
├── requirements.txt           # Python dependencies
├── .env.example               # Template for environment variables
├── .env                       # Your LLM config (git-ignored)
├── .gitignore
├── url_cache.json             # Auto-generated; caches best URL per part number
├── input/
│   └── PartClassifierInput.xlsx   # Sample input file
├── output/                    # Auto-generated; one .xlsx per part class
└── src/
    ├── __init__.py
    ├── llm_client.py          # Unified LLM client (Groq/OpenAI/Anthropic/Ollama)
    ├── part_classifier.py     # LLM-based part classification
    ├── web_scraper.py         # DuckDuckGo search + curl_cffi scraping
    ├── attribute_extractor.py # LLM-based attribute extraction + unit conversion
    ├── attr_schema.py         # Canonical attribute names + alias normalization
    └── excel_handler.py       # Input reader + per-class output writer
```

---

## Supported Part Classes

The agent can classify and extract attributes for any part type. The following classes have predefined canonical attribute schemas for consistent column ordering:

**Washers:** Flat Washer, Fender Washer, Split Lock Washer, Lock Washer, Internal Tooth Lock Washer, External Tooth Lock Washer

**Nuts:** Hex Nut, Lock Nut

**Bolts / Screws:** Hex Bolt, Cap Screw, Set Screw

**Pins:** Dowel Pin, Cotter Pin

Other part types are handled with a generic attribute schema. To add a new class, add its canonical attribute list to `CLASS_SCHEMAS` in `src/attr_schema.py` and any alias variants to `ALIASES`.

---

## Notes

- McMaster-Carr blocks all automated scraping. For McMaster parts, the agent searches for them on trusted distributor mirrors (skdin.com, aftfasteners.com, etc.) which carry the same spec data.
- The `url_cache.json` file is safe to commit -- it only contains public product page URLs and speeds up reruns significantly.
- The `output/` folder is git-ignored and regenerated on each run.
