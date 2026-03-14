# Strategy & Feature Guide -- PartClassifier

## Vision

PartClassifier is an AI-powered mechanical parts classification agent designed for industrial engineering teams managing large inventories of fasteners and mechanical components. It automates the tedious manual process of looking up part specifications from distributor websites, extracting structured attributes, and preparing classification-ready Excel outputs for Teamcenter PLM import.

The agent combines LLM intelligence with multi-source data retrieval -- distributor APIs, stealth web scraping, and intelligent caching -- to process thousands of parts with minimal human intervention. It bridges the gap between unstructured part catalogs and structured PLM classification systems.

## Competitive Landscape

| Approach | Strength | Weakness |
|----------|----------|----------|
| Manual lookup | Accurate, human-verified | Extremely slow (2-5 min/part), doesn't scale |
| Generic web scrapers | Fast, programmable | Blocked by bot detection, no part intelligence |
| PLM vendor tools | Integrated with Teamcenter | Expensive licensing, limited to vendor catalog |
| **PartClassifier** | AI-driven, multi-source, self-classifying | Requires initial setup, LLM costs for large batches |

## Feature Map

### Core Pipeline Features

#### 1. AI Part Classification
- **Entry:** `src/part_classifier.py`
- Classifies part names into categories (Flat Washer, Hex Bolt, Split Lock Washer, etc.)
- Uses configurable LLM (Groq, OpenAI, Anthropic, Ollama)
- 20+ predefined part classes with canonical attribute schemas

#### 2. Multi-Source Spec Lookup
- **Entry:** `src/web_scraper.py`, `src/api_sources.py`
- Priority chain: Distributor APIs -> Stealth Browser -> URL Cache -> DuckDuckGo + curl_cffi -> Stealth Fallback
- DigiKey, Mouser, McMaster-Carr API integrations (all optional)
- CloakBrowser stealth scraping for bot-protected sites (McMaster-Carr, Fastenal, Grainger)
- DuckDuckGo search with spec-keyword scoring algorithm

#### 3. Attribute Extraction & Normalization
- **Entry:** `src/attribute_extractor.py`, `src/attr_schema.py`
- LLM extracts structured key-value attributes from raw web content
- 120+ alias mappings normalize different naming conventions to canonical names
- Automatic unit conversion (inches <-> mm) per part's specified unit

#### 4. Per-Class Excel Output
- **Entry:** `src/excel_handler.py`
- Groups parts by classified type
- Writes one `.xlsx` per class with consistent column headers
- Styled headers (blue fill, white bold), auto-sized columns

### Execution Modes

#### 5. API Key CLI Mode (`main.py`)
- Single-threaded sequential processing
- Configurable LLM provider via `.env`
- Best for: small batches, testing, debugging

#### 6. Streamlit Web UI (`app.py`)
- Interactive provider/model configuration
- File picker with data preview
- Live progress bar and per-part results
- Download buttons for output files
- Best for: non-technical users, demos

#### 7. Claude Code CLI Mode (`main_cc.py`)
- Zero API key requirement (uses `claude` CLI)
- Batch classification: 100 parts per CLI call
- Parallel workers (default 4, configurable)
- Resume capability via `progress_cc.json`
- Best for: large batches (1K-20K+ parts), enterprise environments

### Infrastructure Features

#### 8. URL Caching
- Shared `url_cache.json` across all modes
- Cache-hit fast path skips search entirely
- Dead URL detection and auto-removal
- Safe to commit (public URLs only)

#### 9. Stealth Browser Integration
- **Entry:** `src/stealth_scraper.py`
- CloakBrowser: custom-compiled Chromium with 33 C++ patches
- Bypasses Cloudflare, reCAPTCHA, FingerprintJS
- Direct URL patterns for McMaster, Fastenal, Grainger
- Generic search+scrape fallback for any manufacturer
- Optional -- graceful fallback to curl_cffi if not installed

#### 10. Bot Detection Bypass (curl_cffi)
- Chrome 124 TLS fingerprint impersonation (JA3/JA4)
- Browser-like headers (Accept-Language, Accept)
- Rate limiting (1.5s between DuckDuckGo queries, 30 req/min Mouser)

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.11+ |
| LLM (Groq) | OpenAI SDK | >=1.40.0 |
| LLM (Anthropic) | Anthropic SDK | >=0.40.0 |
| HTTP (TLS stealth) | curl_cffi | >=0.7.0 |
| HTTP (async APIs) | httpx | >=0.27.0 |
| HTML Parsing | BeautifulSoup4 | >=4.12.0 |
| Stealth Browser | CloakBrowser | >=0.3.0 |
| Excel I/O | openpyxl | >=3.1.0 |
| Web UI | Streamlit | >=1.38.0 |
| Env Config | python-dotenv | >=1.0.0 |

## Roadmap

| Phase | Milestones | Status |
|-------|-----------|--------|
| v1.0 | Core pipeline: classify, scrape, extract, write Excel | Done |
| v1.1 | Multi-provider LLM support, Streamlit web UI | Done |
| v1.2 | Distributor APIs (DigiKey, Mouser, McMaster) | Done |
| v1.3 | Claude Code CLI mode with batch + parallel | Done |
| v1.4 | CloakBrowser stealth scraping for bot-protected sites | Done |
| v2.0 | Teamcenter direct import, additional part classes | Planned |

## File Structure

```
PartClassifier/
├── main.py                    # API key mode CLI entry point
├── main_cc.py                 # Claude Code CLI mode entry point (zero-key)
├── app.py                     # Streamlit web UI (1,028 lines)
├── probe_sources.py           # Utility to test distributor sites
├── requirements.txt           # 9 Python dependencies
├── .env.example               # Configuration template
├── .env                       # Runtime config (git-ignored)
├── .gitignore
├── README.md                  # Project documentation
├── COO.md                     # This file -- strategy & features
├── SITECONFIGURATIONS.md      # Setup guide
├── url_cache.json             # URL cache (shared across modes)
├── input/
│   └── PartClassifierInput.xlsx   # Sample input (4 parts)
├── output/                    # Generated Excel files (git-ignored)
├── docs/                      # HTML documentation pages
│   ├── index.html             # Documentation hub
│   ├── README.html            # Project overview landing page
│   ├── COO.html               # Strategy dashboard
│   └── SITECONFIGURATIONS.html # Interactive setup guide
└── src/
    ├── __init__.py
    ├── llm_client.py          # Unified LLM client (192 lines)
    ├── claude_code_client.py  # Claude CLI wrapper (518 lines)
    ├── part_classifier.py     # LLM classification (45 lines)
    ├── web_scraper.py         # Multi-source scraping (341 lines)
    ├── stealth_scraper.py     # CloakBrowser integration (216 lines)
    ├── attribute_extractor.py # LLM extraction + units (140 lines)
    ├── attr_schema.py         # Canonical schemas + aliases (230 lines)
    ├── api_sources.py         # DigiKey/Mouser/McMaster APIs (392 lines)
    ├── excel_handler.py       # Excel read/write (126 lines)
    └── pdf_extractor.py       # PDF text extraction (31 lines, unused)
```
