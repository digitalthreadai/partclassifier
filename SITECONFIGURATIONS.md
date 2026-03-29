# Site Configuration Guide -- PartClassifier

## 1. Python Environment

### Prerequisites
- Python 3.11+ ([python.org](https://www.python.org/downloads/))
- Git (optional, for cloning)
- pip (included with Python)

### Clone and setup

```bash
git clone https://github.com/digitalthreadai/partclassifier.git
cd partclassifier
```

### Create virtual environment (recommended)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
```

### Install dependencies

```bash
pip install -r requirements.txt
```

This installs: `openai`, `openpyxl`, `curl_cffi`, `beautifulsoup4`, `python-dotenv`, `anthropic`, `httpx`, `streamlit`.

CloakBrowser is optional and installed separately (see Section 4).

---

## 2. LLM Provider Configuration (9 Providers)

Copy the example env file and edit:

```bash
cp .env.example .env
```

### Groq (free, recommended to start)

```env
LLM_PROVIDER=groq
LLM_API_KEY=gsk_your_groq_key_here
```

Get key: https://console.groq.com/keys
Default model: `llama-3.3-70b-versatile`

### OpenAI

```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-your_openai_key_here
LLM_MODEL=gpt-4o
```

Get key: https://platform.openai.com/api-keys

### Anthropic (Claude)

```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-your_anthropic_key_here
LLM_MODEL=claude-sonnet-4-20250514
```

Get key: https://console.anthropic.com/settings/keys
Other models: `claude-opus-4-20250514`, `claude-haiku-4-5-20251001`

### Azure OpenAI (enterprise)

```env
LLM_PROVIDER=azure_openai
LLM_API_KEY=your_azure_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
```

Get access: https://portal.azure.com

### AWS Bedrock (enterprise)

```env
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
```

No API key needed -- uses default AWS credential chain (env vars, `~/.aws/credentials`, IAM role).

Optional explicit credentials:
```env
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
```

### Ollama (local, free)

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
```

Install Ollama: https://ollama.ai
Then: `ollama serve` and `ollama pull llama3.1`

### Custom OpenAI-compatible API

```env
LLM_PROVIDER=custom
LLM_API_KEY=your_key
LLM_BASE_URL=https://your-api-endpoint.com/v1
LLM_MODEL=your-model-name
```

### Azure AI Foundry (enterprise Claude)

```env
LLM_PROVIDER=azure_foundry
LLM_API_KEY=your_foundry_api_key
LLM_BASE_URL=https://your-resource.services.ai.azure.com/models
LLM_MODEL=claude-sonnet-4-20250514
```

Access via Azure AI Foundry portal. Uses the `anthropic[bedrock]` SDK internally (AnthropicFoundry client).
Set `LLM_BASE_URL` to your Foundry endpoint — do not append path suffixes.

### Claude Code CLI (zero API keys)

No `.env` configuration required. Uses the `claude` CLI installed on PATH.

```bash
python main_cc.py                # 4 parallel workers
python main_cc.py --workers 8    # 8 workers (faster)
```

Works with any backend configured in Claude Code: Anthropic, Azure, AWS Bedrock, etc.

---

## 3. Distributor API Keys (all optional)

Higher-quality structured data. When an API returns 3+ attributes, LLM extraction is skipped entirely.

### DigiKey (free, OAuth2)

Register at [developer.digikey.com](https://developer.digikey.com):

```env
DIGIKEY_CLIENT_ID=your_client_id
DIGIKEY_CLIENT_SECRET=your_client_secret
```

OAuth2 tokens are auto-cached and refreshed.

### Mouser (free, API key)

Register at [api.mouser.com](https://api.mouser.com):

```env
MOUSER_API_KEY=your_api_key
```

Rate limited: 30 req/min (auto-throttled).

### McMaster-Carr (by request, mTLS)

Email `eprocurement@mcmaster.com` for mTLS access:

```env
MCMASTER_BEARER_TOKEN=your_token
MCMASTER_CLIENT_CERT=path/to/client.pem
MCMASTER_CLIENT_KEY=path/to/client-key.pem
```

---

## 4. Stealth Browser (optional)

CloakBrowser enables scraping bot-protected sites like McMaster-Carr, Fastenal, and Grainger.

```bash
pip install cloakbrowser
```

First run downloads ~200MB Chromium binary automatically. To disable:

```env
STEALTH_BROWSER_ENABLED=false
```

Features:
- 33 C++ source-level patches to Chromium
- Bypasses Cloudflare, reCAPTCHA v3 (0.9 score), FingerprintJS, Turnstile
- Fresh browser context per scrape (no session fingerprinting)
- Direct URL patterns for McMaster-Carr, Fastenal, Grainger

---

## 5. Input Excel Preparation

Place your file at `input/PartClassifierInput.xlsx`.

Required columns (exact names):

| Column | Description | Example |
|--------|-------------|---------|
| Part Number | Internal part number | 900401 |
| Part Name | Descriptive name (used for classification) | WASHER, #5, INT TOOTH |
| Manufacturer Part Number | Used for web search | 98449A515 |
| Manufacturer Name | Manufacturer or distributor | MCMASTER CARR SUPPLY |
| Unit of Measure | Target unit for output values | inches or mm |

A sample file with 4 parts is included in the repo.

### Classification Schema

The JSON schema files in `schema/` define all part classes, canonical attributes, and alias mappings. See Section 10 for details.

---

## 6. Environment Variables Reference

| Variable | Required | Description | Where to Get |
|----------|----------|-------------|--------------|
| `LLM_PROVIDER` | Yes (API key mode) | groq, openai, anthropic, azure_openai, bedrock, ollama, custom | Choose your provider |
| `LLM_API_KEY` | Yes* | Provider API key (*not needed for Ollama/Bedrock) | Provider console |
| `LLM_MODEL` | No | Override default model | Provider docs |
| `LLM_BASE_URL` | No | Custom endpoint (custom provider only) | Your API admin |
| `AZURE_OPENAI_ENDPOINT` | Azure only | Azure resource endpoint | portal.azure.com |
| `AZURE_OPENAI_API_VERSION` | No | API version (default: 2024-12-01-preview) | Azure docs |
| `AZURE_OPENAI_DEPLOYMENT` | No | Deployment name | Azure portal |
| `AWS_ACCESS_KEY_ID` | No | AWS access key (Bedrock) | AWS console |
| `AWS_SECRET_ACCESS_KEY` | No | AWS secret key (Bedrock) | AWS console |
| `AWS_REGION` | No | AWS region (default: us-east-1) | AWS console |
| `DIGIKEY_CLIENT_ID` | No | DigiKey OAuth2 client ID | developer.digikey.com |
| `DIGIKEY_CLIENT_SECRET` | No | DigiKey OAuth2 secret | developer.digikey.com |
| `MOUSER_API_KEY` | No | Mouser Search API key | api.mouser.com |
| `MCMASTER_BEARER_TOKEN` | No | McMaster API bearer token | eprocurement@mcmaster.com |
| `MCMASTER_CLIENT_CERT` | No | Path to McMaster client cert | eprocurement@mcmaster.com |
| `MCMASTER_CLIENT_KEY` | No | Path to McMaster client key | eprocurement@mcmaster.com |
| `STEALTH_BROWSER_ENABLED` | No | true/false to toggle CloakBrowser (default: true) | N/A |
| `SSL_VERIFY` | No | true/false to toggle SSL certificate verification (default: true). Set to false for internal/self-signed certs | N/A |
| `GROQ_API_KEY` | No | Legacy fallback (still works) | console.groq.com |

---

## 7. Running the Agent

### Option A: Streamlit Web UI

```bash
streamlit run app.py
```

Open http://localhost:8501. Configure provider in sidebar, select input file, click Run.

### Option B: API Key CLI

```bash
python main.py
python main.py --input path/to/input.xlsx --output path/to/output/
python main.py --no-cache        # bypass LLM cache
python main.py --clear-cache     # delete cache before run
python main.py --fresh           # ignore previous progress, start from scratch
```

Requires `.env` configured. Processes all parts sequentially with resume capability.

### Option C: Claude Code CLI (zero API keys)

```bash
python main_cc.py                # 4 parallel workers
python main_cc.py --workers 8    # 8 workers (faster)
python main_cc.py --fresh        # ignore previous progress
python main_cc.py --workers 1    # sequential mode (for debugging)
```

Requires `claude` CLI installed and on PATH. No `.env` needed.

---

## 8. Output

Output files appear in `output/`, one per part class:

```
output/
  Flat Washer.xlsx
  Split Lock Washer.xlsx
  Internal Tooth Lock Washer.xlsx
  Deep Groove Ball Bearing.xlsx
  Tube Fitting.xlsx
```

Each file contains: original input columns + Part Class + TC Class ID (looked up from classid in `schema/Classes.json`, checked first before any other source) + Source URL + extracted attributes with canonical column names (schema-ordered). Unit of Measure conversion respects an as-is mode: if the input UoM matches the source data, values are kept as-is without conversion.

---

## 9. Cache Management

### URL Cache (`url_cache.json`)
- Maps manufacturer part numbers to best source URLs
- 30-day TTL with automatic expiration
- Bad-entry eviction: removes URLs that returned no useful content
- Shared across all execution modes
- Coverage improves with each run as cache warms
- Safe to commit (public URLs only)

### LLM Cache (`llm_cache.json`)
- Classification cache: 90-day TTL
- Extraction cache: 30-day TTL
- Thread-safe with atomic writes (Windows-safe via tempfile + os.replace)
- Use `--no-cache` to bypass, `--clear-cache` to delete

### Metrics History (`metrics_history.json`)
- Appended after each run
- Tracks quality, cache effectiveness, regex/LLM agreement, timing
- Use for trend analysis across multiple runs

---

## 10. Classification Schema

### JSON Schema (Required -- `schema/Classes.json` + `schema/Attributes.json`)

The schema source with Teamcenter-compatible hierarchical class trees. Both files are required -- there is no Excel or hardcoded fallback.

- **`schema/Classes.json`** -- 93 classes with ICM-format IDs matching Teamcenter classid. Parent-child tree with attribute inheritance. Each class has: id, classid, name, aliases, attributeslist (numeric attribute IDs), children.
- **`schema/Attributes.json`** -- 46 attributes with 5-digit numeric IDs matching Teamcenter attribute IDs. Each attribute has: name, shortname, aliases, unitOfMeasure (multi-value array), range, LOV values, keyLOVID.

**Attribute inheritance:** Child classes automatically inherit all ancestor attributes.

**LOV normalization:** Extracted values are matched to Teamcenter LOV entries (e.g., "Stainless Steel" maps to "StainlessSteel").

### PLMXML to JSON Converter

To generate JSON schema files from Teamcenter PLMXML exports:

```bash
python plmxml_to_json.py --plmxml export.xml --output schema/

# With SML attribute definitions:
python plmxml_to_json.py --plmxml export.xml --sml attributes.xml --output schema/

# Dry run (preview without writing):
python plmxml_to_json.py --plmxml export.xml --dry-run

# Merge with existing JSON files:
python plmxml_to_json.py --plmxml export.xml --output schema/ --merge

# Demo mode (generate sample output):
python plmxml_to_json.py --demo
```

The converter parses `<AdminClass>` and `<DictionaryAttribute>` tags (namespace-agnostic), reconstructs the hierarchical tree, and resolves attribute→format→KeyLOV chains including inline `<KeyLOV>` sections with `<Key>`/`<Value>` sibling pairs. Zero external dependencies (stdlib only).

### Schema Generation (`generate_schema.py`)

A unified tool that generates both alias and classification hint files from the JSON schema using LLM inference. Uses the same `.env` as `main.py`.

```bash
python generate_schema.py              # generate both
python generate_schema.py --aliases    # aliases.json only
python generate_schema.py --hints      # classification_hints.json only
python generate_schema.py --merge      # fill gaps, keep manual edits
```

### Alias Configuration (`schema/aliases.json`)

The alias system maps LLM-extracted attribute names to TC canonical names. `aliases.json` wins over all other alias sources in the JSON schema.

The file has three sections you can edit manually at any time:

```json
{
  "attribute_aliases": {
    "Inner Diameter": ["ID", "I.D.", "Bore", "Bore Diameter"],
    "Thread Size":    ["Screw Size", "Nominal Size", "Nominal Diameter"]
  },
  "class_aliases": {
    "Flat Washer": ["flat wshr", "fender washer", "plain washer"]
  },
  "class_attribute_overrides": {
    "Bolt":    {"size": "Thread Size", "dia": "Thread Size"},
    "Washer":  {"size": "Outer Diameter"}
  }
}
```

The `shortname` field from `Attributes.json` is automatically loaded as an alias (e.g., shortname `"ID"` -> `"Inner Diameter"`) without any manual config.

### Classification Hints (`schema/classification_hints.json`)

LLM-generated hints that help the classifier distinguish between similar part classes. Each entry maps a class name to a set of distinguishing keywords, typical attributes, and disambiguation notes. Generated by `generate_schema.py --hints` and loaded automatically at classification time.

### Attribute-Fit Validation (`src/class_validator.py`)

The classification pipeline uses attribute-fit scoring to validate and potentially reclassify parts:

1. **Class-blind LLM extraction** -- The LLM extracts all attributes it can find from the scraped content, without being told which class the part belongs to. This avoids confirmation bias.

2. **Attribute-fit scoring** -- Each candidate class is scored by how many of the extracted attributes match its schema. A dynamic set of "universal" attributes (common across many classes) is computed and excluded from scoring to prevent them from inflating every class equally.

3. **Reclassification** -- If a different class scores higher than the original classification by at least `MIN_ADVANTAGE=2` attribute points, the part is reclassified to the better-fitting class.

4. **Abstain mechanism** -- If no class achieves a meaningful fit score, the system can abstain from classification rather than forcing a poor match.

After validation, run the classifier normally -- `aliases.json` and `classification_hints.json` are loaded automatically at startup.

```bash
python main.py
# or
python main_cc.py
```

### Adding a New Part Class

1. Add to `schema/Classes.json`:
   - Add a new entry with classid, name, aliases, and attributeslist (numeric attribute IDs)
   - Child classes inherit parent attributes automatically

2. Add any new attributes to `schema/Attributes.json` if they do not already exist.

3. Regenerate aliases and hints:
   ```bash
   python generate_schema.py --merge
   ```

4. Optionally add abbreviation aliases to `CLASS_ALIASES` in `src/class_extractor.py` for deterministic classification:
```python
"my alias": "My New Class",
```

---

## 11. Pipeline Optimization Features

### Batch Classification
In `main.py`, the `PartClassifier.classify_batch()` method classifies up to 50 parts per LLM call. In `main_cc.py`, batch size is 100 parts per CLI call (75x faster than individual calls). Parts that fail batch parsing fall back to individual classification.

### Regex Pre-Extraction
Before each LLM extraction call, `regex_extractor.py` attempts pattern-based extraction. Pre-extracted values are sent to the LLM for validation and gap-filling via the hybrid prompt (priority schema hints + maximize coverage), reducing the LLM's workload and improving accuracy.

### Deterministic Classification
`class_extractor.py` attempts to classify parts from web content alone (breadcrumbs, labels, titles, URLs) with 95% accuracy. Only when this fails does the pipeline make an LLM call, saving tokens on parts with clear category signals.

### Manufacturer Rotation
`shared.py:rotate_manufacturers()` reorders parts so requests to the same manufacturer are spread apart, reducing the risk of bot detection and rate limiting.

### Content Cleaning
`content_cleaner.py` extracts structured data from HTML tables and applies smart truncation (3K tables / 5K text / 8K combined) to ensure specs are prioritized over navigation boilerplate.

---

## 12. Deployment

### Local Development
No special deployment needed. Run directly with Python.

### Production (large batches)
- Use `main_cc.py` with `--workers 8` for maximum throughput
- Ensure `claude` CLI is configured for your enterprise backend (Azure, etc.)
- Progress auto-saves; safe to interrupt and resume
- Output files written every 50 parts (main_cc.py) or 10 parts (main.py)
- URL cache warms over multiple runs for improving coverage

### Docker (optional)
No Dockerfile is included yet. For containerization:
- Base image: `python:3.11-slim`
- Install requirements + optional cloakbrowser
- Mount `input/` and `output/` volumes

---

## Checklist

### Initial Setup
- [ ] Python 3.11+ installed
- [ ] Repository cloned
- [ ] Virtual environment created and activated
- [ ] `pip install -r requirements.txt` completed
- [ ] `.env` file created from `.env.example`
- [ ] LLM provider and API key configured

### Optional Enhancements
- [ ] DigiKey API configured (OAuth2)
- [ ] Mouser API configured
- [ ] McMaster API configured (mTLS)
- [ ] CloakBrowser installed (`pip install cloakbrowser`)
- [ ] Azure OpenAI configured (enterprise)
- [ ] AWS Bedrock configured (enterprise)
- [ ] JSON schema files in `schema/` reviewed or generated from PLMXML (if using Teamcenter)
- [ ] Aliases and hints generated (`python generate_schema.py`)

### First Run
- [ ] Input Excel placed in `input/` folder
- [ ] Ran classification (any mode)
- [ ] Verified output files in `output/`
- [ ] Checked TC Class ID column in output
- [ ] Checked attribute accuracy
- [ ] Reviewed metrics summary
