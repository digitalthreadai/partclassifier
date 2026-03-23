# Strategy & Feature Guide -- PartClassifier

## Vision

PartClassifier is an AI-powered mechanical parts classification agent designed for industrial engineering teams managing large inventories of fasteners, bearings, fittings, sensors, and other mechanical components. It automates the tedious manual process of looking up part specifications from distributor websites, extracting structured attributes, and preparing classification-ready Excel outputs for Teamcenter PLM import.

The agent combines deterministic pattern matching, regex pre-extraction, and LLM intelligence with multi-source data retrieval -- distributor APIs, stealth web scraping, and intelligent caching -- to process thousands of parts with minimal human intervention. A six-step pipeline ensures maximum accuracy: web search, deterministic classification from content, regex pre-extraction, LLM validation, and per-class Excel output.

## Competitive Landscape

| Approach | Strength | Weakness |
|----------|----------|----------|
| Manual lookup | Accurate, human-verified | Extremely slow (2-5 min/part), doesn't scale |
| Generic web scrapers | Fast, programmable | Blocked by bot detection, no part intelligence |
| PLM vendor tools | Integrated with Teamcenter | Expensive licensing, limited to vendor catalog |
| **PartClassifier** | AI-driven, multi-source, self-classifying, 60+ part classes | Requires initial setup, LLM costs for large batches |

## Architecture Overview

```
Input Excel
    |
    v
[ExcelHandler] --> reads Part Number, Part Name, Mfg Part Number, Mfg Name, Unit
    |
    v
[Manufacturer Rotation] --> reorders parts to avoid same-manufacturer adjacency
    |
    v
[Multi-Tier Search] --> DigiKey/Mouser/McMaster APIs
                    --> CloakBrowser stealth scraping
                    --> URL cache fast path
                    --> DuckDuckGo + curl_cffi
                    --> Stealth fallback
    |
    v
[Deterministic Classification] --> breadcrumbs, category labels, URL paths, aliases
    |  (fallback: LLM cache -> LLM classify)
    v
[Regex Pre-Extraction] --> tables, key-value patterns, standards, materials
    |
    v
[LLM Validation + Gap Fill] --> validates regex values, extracts missing attrs
    |                            temperature=0, deterministic
    v
[Attribute Normalization] --> 500+ aliases -> canonical names per class
    |
    v
[Per-Class Excel Output] --> styled headers, auto-sized columns
```

## Feature Map

### Core Pipeline Features

#### 1. Multi-Tier Web Search
- **Entry:** `src/web_scraper.py`, `src/api_sources.py`, `src/stealth_scraper.py`
- **Priority chain:** Distributor APIs -> Stealth Browser (direct URL) -> URL Cache -> DuckDuckGo + curl_cffi -> Stealth Browser (search fallback)
- DigiKey, Mouser, McMaster-Carr API integrations (all optional)
- CloakBrowser stealth scraping for bot-protected sites (McMaster-Carr, Fastenal, Grainger)
- DuckDuckGo search with spec-keyword scoring algorithm
- Preferred trusted domains scored higher (skdin.com, aftfasteners.com, boltdepot.com, fastenal.com, etc.)

#### 2. Deterministic Classification from Web Content
- **Entry:** `src/class_extractor.py`
- Pattern-based classification that requires no LLM call
- Scans breadcrumbs, category labels, page titles, URL paths, and keyword density
- 90+ class aliases map abbreviations to canonical names (e.g., "shcs" -> "Socket Head Cap Screw")
- Parent-child specificity resolution (e.g., "Washer" demoted when "Split Lock Washer" also matches)
- Confidence threshold (score >= 4) before accepting a deterministic match
- Falls back to LLM classification only when pattern matching is inconclusive

#### 3. LLM Part Classification
- **Entry:** `src/part_classifier.py`
- Classifies part names into 60+ categories using configurable LLM
- Batch classification: 50 parts per LLM call (95% token savings vs individual calls)
- Individual fallback for any parts that fail batch parsing
- LLM cache with 90-day TTL avoids re-classifying known parts

#### 4. Regex Pre-Extraction
- **Entry:** `src/regex_extractor.py`
- Pattern-based attribute extraction from scraped content before LLM call
- Extracts from: HTML tables (highest reliability), key-value patterns, standards (DIN, ASME, ISO), materials (18-8 SS, 304L, Carbon Steel, Viton, etc.)
- Builds label patterns dynamically from the ALIASES dictionary
- Agreement tracking: compares regex vs LLM results to measure confidence
- Pre-extracted values sent to LLM for validation, not as replacements

#### 5. Table-Aware Content Extraction
- **Entry:** `src/content_cleaner.py`
- Extracts HTML tables as structured key-value data before cleaning body text
- Handles header-row + data-row tables and two-column label-value tables
- Spec table detection via keyword matching (diameter, thickness, material, etc.)
- Tables prioritized in combined output so specs are never cut off by navigation boilerplate
- Configurable limits: 3000 chars tables, 5000 chars text, 8000 chars combined

#### 6. LLM Attribute Extraction & Validation
- **Entry:** `src/attribute_extractor.py`
- LLM extracts structured key-value attributes from raw web content
- When regex pre-extracted values exist, LLM validates and fills gaps (not full extraction)
- Automatic unit conversion (inches <-> mm) per part's specified unit
- Validation retry: if >50% of schema attributes missing, targeted re-extraction for just the missing ones
- Temperature=0 for deterministic, reproducible output

#### 7. Canonical Attribute Normalization
- **Entry:** `src/attr_schema.py`
- 60+ part classes defined in KNOWN_CLASSES spanning fasteners, bearings, seals, fittings, pneumatics, sensors, vacuum components
- 15 class-specific schemas with ordered canonical attribute lists
- 500+ alias mappings normalize different naming conventions (e.g., "Screw Size", "Thread Size", "For Screw Size" all map to "Screw Size")
- DigiKey/Mouser API parameter names included in alias mappings
- Default schema for classes without specific definitions
- Fuzzy schema matching for partial class name matches

#### 8. Per-Class Excel Output
- **Entry:** `src/excel_handler.py`
- Groups parts by classified type
- Writes one `.xlsx` per class with consistent column headers
- Styled headers (blue fill, white bold), auto-sized columns
- Preserves original input columns + Part Class + Source URL + extracted attributes

### Execution Modes

#### 9. API Key CLI Mode (`main.py`)
- Single-threaded sequential processing with asyncio
- Configurable LLM provider via `.env` (7 providers supported)
- Resume capability via `progress.json` checkpoint after each part
- Periodic Excel writes every 10 parts
- Retry logic with exponential backoff for timeouts and rate limits
- CLI flags: `--input`, `--output`, `--no-cache`, `--clear-cache`
- Best for: small batches, testing, debugging

#### 10. Streamlit Web UI (`app.py`)
- Interactive provider/model configuration in sidebar
- File picker with data preview
- Live progress bar and per-part results
- Download buttons for output files
- Writes `.env` automatically from sidebar configuration
- Best for: non-technical users, demos

#### 11. Claude Code CLI Mode (`main_cc.py`)
- Zero API key requirement (uses `claude` CLI on PATH)
- Batch classification: 100 parts per CLI call
- Parallel workers (default 4, configurable with `--workers`)
- Resume capability via `progress_cc.json` (or provider-specific progress files)
- Intermediate Excel writes every 50 parts
- Per-part error isolation (one failure doesn't stop the batch)
- Ctrl+C safe (saves progress and writes partial output on interrupt)
- Best for: large batches (1K-20K+ parts), enterprise environments with Claude Code on Azure

### Infrastructure Features

#### 12. LLM Response Cache
- **Entry:** `src/llm_cache.py`
- Thread-safe cache with atomic writes (Windows-safe via tempfile + os.replace)
- Classification cache: 90-day TTL, keyed on normalized input text (MD5)
- Extraction cache: 30-day TTL, keyed on mfg_part_num + part_class + content hash
- Eliminates redundant LLM calls for previously-seen parts
- CLI flags: `--no-cache` to bypass, `--clear-cache` to delete before run

#### 13. URL Caching
- **Entry:** `src/shared.py` (load_cache, save_cache)
- Shared `url_cache.json` across all execution modes
- 30-day TTL with timestamp migration from legacy format
- Cache-hit fast path skips search entirely
- Atomic writes for Windows safety
- Safe to commit (public URLs only)

#### 14. Metrics Tracking
- **Entry:** `src/metrics.py`
- Tracks per-run quality metrics: classification rate, attribute rate, zero-attr parts
- Cache effectiveness: classify hits, extract hits
- Regex metrics: parts with data, total attrs, regex/LLM agreement rate
- LLM call counts: classify calls, extract calls
- Timing: elapsed seconds, seconds per part
- Appends to `metrics_history.json` for trend analysis

#### 15. Stealth Browser Integration
- **Entry:** `src/stealth_scraper.py`
- CloakBrowser: custom-compiled Chromium with 33 C++ source-level patches
- Bypasses Cloudflare, reCAPTCHA v3 (0.9 score), FingerprintJS, Turnstile
- Direct URL patterns for McMaster-Carr, Fastenal, Grainger
- Fresh browser context per scrape to avoid session fingerprinting
- Generic search+scrape fallback for any manufacturer
- Optional -- graceful fallback to curl_cffi if not installed

#### 16. Bot Detection Bypass (curl_cffi)
- Chrome 124 TLS fingerprint impersonation (JA3/JA4)
- Browser-like headers (Accept-Language, Accept)
- Rate limiting (1.5s between DuckDuckGo queries, 30 req/min Mouser)

#### 17. Manufacturer Rotation
- **Entry:** `src/shared.py` (rotate_manufacturers)
- Round-robin interleave by manufacturer name
- Spaces out requests to the same site to reduce bot detection risk
- Largest manufacturer buckets spread widest

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.11+ |
| LLM (Groq/OpenAI/Ollama) | OpenAI SDK | >=1.40.0 |
| LLM (Anthropic/Bedrock) | Anthropic SDK | >=0.40.0 |
| HTTP (TLS stealth) | curl_cffi | >=0.7.0 |
| HTTP (async APIs) | httpx | >=0.27.0 |
| HTML Parsing | BeautifulSoup4 | >=4.12.0 |
| Stealth Browser | CloakBrowser | >=0.3.0 (optional) |
| Excel I/O | openpyxl | >=3.1.0 |
| Web UI | Streamlit | >=1.38.0 |
| Env Config | python-dotenv | >=1.0.0 |

## LLM Providers

| Provider | Default Model | API Key Required | Notes |
|----------|--------------|------------------|-------|
| Groq | llama-3.3-70b-versatile | Yes (free) | Fastest inference, recommended to start |
| OpenAI | gpt-4o | Yes | GPT-4o, GPT-4-turbo, GPT-3.5-turbo |
| Anthropic | claude-sonnet-4-20250514 | Yes | Claude Opus, Sonnet, Haiku |
| Azure OpenAI | gpt-4o | Yes | Enterprise, requires AZURE_OPENAI_ENDPOINT |
| AWS Bedrock | anthropic.claude-sonnet-4-20250514-v1:0 | No (AWS creds) | Uses default AWS credential chain |
| Ollama | llama3.1 | No | Local inference, free, requires ollama serve |
| Custom | gpt-4o | Varies | Any OpenAI-compatible endpoint via LLM_BASE_URL |

## Roadmap

| Phase | Milestones | Status |
|-------|-----------|--------|
| v1.0 | Core pipeline: classify, scrape, extract, write Excel | Done |
| v1.1 | Multi-provider LLM support (7 providers), Streamlit web UI | Done |
| v1.2 | Distributor APIs (DigiKey, Mouser, McMaster) | Done |
| v1.3 | Claude Code CLI mode with batch + parallel workers | Done |
| v1.4 | CloakBrowser stealth scraping, manufacturer rotation | Done |
| v1.5 | Deterministic classification, regex pre-extraction, LLM cache, metrics | Done |
| v2.0 | Teamcenter direct import, additional part classes | Planned |

## File Structure

```
PartClassifier/
├── main.py                    # API key mode CLI entry point
├── main_cc.py                 # Claude Code CLI mode entry point (zero-key)
├── app.py                     # Streamlit web UI
├── requirements.txt           # Python dependencies
├── .env.example               # Configuration template
├── .env                       # Runtime config (git-ignored)
├── .gitignore
├── README.md                  # Project overview
├── COO.md                     # This file -- strategy & features
├── SITECONFIGURATIONS.md      # Setup guide
├── url_cache.json             # URL cache (shared across modes, 30-day TTL)
├── llm_cache.json             # LLM response cache (90/30-day TTL)
├── metrics_history.json       # Run metrics history
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
    ├── llm_client.py          # Unified async LLM client (7 providers)
    ├── claude_code_client.py  # Claude CLI wrapper (no API keys)
    ├── part_classifier.py     # LLM classification + batch (50/call)
    ├── web_scraper.py         # Multi-tier content lookup
    ├── stealth_scraper.py     # CloakBrowser integration
    ├── api_sources.py         # DigiKey/Mouser/McMaster APIs
    ├── attribute_extractor.py # LLM extraction + unit conversion
    ├── class_extractor.py     # Deterministic class from web content
    ├── content_cleaner.py     # HTML table extraction + text cleaning
    ├── regex_extractor.py     # Pattern pre-extraction + agreement
    ├── attr_schema.py         # 60+ classes, 500+ aliases
    ├── llm_cache.py           # LLM response cache (thread-safe)
    ├── metrics.py             # Run metrics tracker
    ├── shared.py              # Manufacturer rotation, cache I/O, atomic writes
    └── excel_handler.py       # Excel read/write
```
