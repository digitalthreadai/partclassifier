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

This installs 9 packages: `openai`, `openpyxl`, `curl_cffi`, `beautifulsoup4`, `python-dotenv`, `anthropic`, `httpx`, `streamlit`, `cloakbrowser`.

---

## 2. LLM Provider Configuration

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

---

## 3. Distributor API Keys (all optional)

Higher-quality structured data. Bypasses LLM extraction when 3+ attributes found.

### DigiKey (free)

Register at [developer.digikey.com](https://developer.digikey.com):

```env
DIGIKEY_CLIENT_ID=your_client_id
DIGIKEY_CLIENT_SECRET=your_client_secret
```

OAuth2 tokens are auto-cached and refreshed.

### Mouser (free)

Register at [api.mouser.com](https://api.mouser.com):

```env
MOUSER_API_KEY=your_api_key
```

Rate limited: 30 req/min (auto-throttled).

### McMaster-Carr (by request)

Email `eprocurement@mcmaster.com` for mTLS access:

```env
MCMASTER_BEARER_TOKEN=your_token
MCMASTER_CLIENT_CERT=path/to/client.pem
MCMASTER_CLIENT_KEY=path/to/client-key.pem
```

---

## 4. Stealth Browser (optional)

CloakBrowser enables scraping bot-protected sites like McMaster-Carr directly.

```bash
pip install cloakbrowser
```

First run downloads ~200MB Chromium binary automatically. To disable:

```env
STEALTH_BROWSER_ENABLED=false
```

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

---

## 6. Environment Variables Reference

| Variable | Required | Description | Where to Get |
|----------|----------|-------------|--------------|
| `LLM_PROVIDER` | Yes (API key mode) | groq, openai, anthropic, ollama, custom | Choose your provider |
| `LLM_API_KEY` | Yes* | Provider API key (*not needed for Ollama) | Provider console |
| `LLM_MODEL` | No | Override default model | Provider docs |
| `LLM_BASE_URL` | No | Custom endpoint (custom provider only) | Your API admin |
| `DIGIKEY_CLIENT_ID` | No | DigiKey OAuth2 client ID | developer.digikey.com |
| `DIGIKEY_CLIENT_SECRET` | No | DigiKey OAuth2 secret | developer.digikey.com |
| `MOUSER_API_KEY` | No | Mouser Search API key | api.mouser.com |
| `MCMASTER_BEARER_TOKEN` | No | McMaster API bearer token | eprocurement@mcmaster.com |
| `MCMASTER_CLIENT_CERT` | No | Path to McMaster client cert | eprocurement@mcmaster.com |
| `MCMASTER_CLIENT_KEY` | No | Path to McMaster client key | eprocurement@mcmaster.com |
| `STEALTH_BROWSER_ENABLED` | No | true/false to toggle CloakBrowser | N/A (default: true) |
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
```

Requires `.env` configured. Processes all parts sequentially.

### Option C: Claude Code CLI (zero API keys)

```bash
python main_cc.py                # 4 parallel workers
python main_cc.py --workers 8   # 8 workers (faster)
python main_cc.py --fresh        # ignore previous progress
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
```

Each file contains: original input columns + Part Class + Source URL + extracted attributes with canonical column names.

---

## 9. Adding New Part Classes

Edit `src/attr_schema.py`:

1. Add canonical attribute list to `CLASS_SCHEMAS`:
```python
"My New Class": [
    "Attribute 1", "Attribute 2", "Material", "Finish",
],
```

2. Add any alias variants to `ALIASES`:
```python
"alt name for attr 1": "Attribute 1",
```

---

## 10. Deployment

### Local Development
No special deployment needed. Run directly with Python.

### Production (large batches)
- Use `main_cc.py` with `--workers 8` for maximum throughput
- Ensure `claude` CLI is configured for your enterprise backend (Azure, etc.)
- Progress auto-saves; safe to interrupt and resume
- Output files written every 50 parts

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
- [ ] DigiKey API configured
- [ ] Mouser API configured
- [ ] McMaster API configured
- [ ] CloakBrowser installed (`pip install cloakbrowser`)

### First Run
- [ ] Input Excel placed in `input/` folder
- [ ] Ran classification (any mode)
- [ ] Verified output files in `output/`
- [ ] Checked attribute accuracy
