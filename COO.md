# Strategy & Feature Guide -- PartClassifier

## Vision

PartClassifier is a production-grade AI agent for mechanical part classification and attribute extraction, built for industrial engineering teams managing large inventories of fasteners, bearings, fittings, sensors, and other mechanical components. It automates the tedious manual process of looking up part specifications from distributor websites, extracting structured attributes, and preparing classification-ready Excel outputs for Teamcenter PLM import.

The agent combines deterministic pattern matching, regex pre-extraction, and LLM intelligence with multi-source data retrieval -- distributor APIs, stealth web scraping, and intelligent caching -- to process thousands of parts with minimal human intervention. A six-step pipeline ensures maximum accuracy: multi-tier search, deterministic classification from web content (95% accuracy), regex pre-extraction, LLM validation with hybrid prompts (priority schema hints + maximize coverage), canonical normalization via 500+ alias mappings, and per-class Excel output with TC Class ID mapping.

**Key stats:** 7,031 LOC across 17 modules, 8 LLM providers, 3 distributor APIs, 81 part classes, 46 attributes, 169 aliases in Excel-based schema, 21 production-ready bug fixes.

## Competitive Landscape

| Approach | Strength | Weakness |
|----------|----------|----------|
| Manual lookup | Accurate, human-verified | Extremely slow (2-5 min/part), doesn't scale |
| Generic web scrapers | Fast, programmable | Blocked by bot detection, no part intelligence |
| PLM vendor tools | Integrated with Teamcenter | Expensive licensing, limited to vendor catalog |
| **PartClassifier** | AI-driven, multi-source, self-classifying, 81 part classes, 8 LLM providers | Requires initial setup, LLM costs for large batches |

## Benchmark Results (44 parts)

| Configuration | Coverage | Avg Attrs/Part | Notes |
|--------------|----------|----------------|-------|
| Groq V8 | 86% | 14.1 | 5x improvement over baseline |
| Opus V8c (warm cache) | 93% | 5.7 | 39% improvement over cold start |

Coverage improves with each run due to URL cache warming. The URL cache with TTL and bad-entry eviction ensures that every run discovers better source URLs for future runs.

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
[Multi-Tier Search] --> DigiKey/Mouser/McMaster APIs (structured data)
                    --> CloakBrowser stealth scraping (bot-protected sites)
                    --> URL cache fast path (30-day TTL)
                    --> DuckDuckGo + curl_cffi (Chrome 124 TLS fingerprint)
                    --> Stealth fallback (generic search+scrape)
    |
    v
[Content Cleaner] --> HTML table extraction + smart truncation (3K/5K/8K limits)
    |
    v
[Deterministic Classification] --> breadcrumbs, category labels, URL paths, aliases
    |  (95% accuracy, fallback: LLM cache -> batch LLM classify)
    v
[Regex Pre-Extraction] --> tables, key-value patterns, standards (DIN/ASME/ISO), materials
    |
    v
[LLM Validation + Gap Fill] --> hybrid prompt with priority schema hints + maximize coverage
    |                            temperature=0, deterministic, retry for missing attrs
    v
[Attribute Normalization] --> 500+ aliases -> canonical names per class, schema-ordered
    |
    v
[Per-Class Excel Output] --> styled headers, auto-sized columns, TC Class ID
```

## Feature Map

### Core Pipeline Features

#### 1. Multi-Tier Web Search
- **Entry:** `src/web_scraper.py`, `src/api_sources.py`, `src/stealth_scraper.py`
- **7-tier priority chain:** Distributor APIs -> Stealth Browser (direct URL) -> URL Cache -> DuckDuckGo + curl_cffi -> Stealth Browser (search fallback) -> URL cache fallback -> Part name mining
- DigiKey (OAuth2), Mouser (API key), McMaster-Carr (mTLS) API integrations (all optional)
- CloakBrowser stealth scraping for bot-protected sites (McMaster-Carr, Fastenal, Grainger)
- DuckDuckGo search with spec-keyword scoring algorithm
- Preferred trusted domains scored higher (skdin.com, aftfasteners.com, boltdepot.com, fastenal.com, etc.)
- URL cache with 30-day TTL + bad-entry eviction (coverage improves with each run)

#### 2. Content Cleaning & Table Extraction
- **Entry:** `src/content_cleaner.py`
- Extracts HTML tables as structured key-value data before cleaning body text
- Handles header-row + data-row tables and two-column label-value tables
- Spec table detection via keyword matching (diameter, thickness, material, etc.)
- Tables prioritized in combined output so specs are never cut off by navigation boilerplate
- Smart truncation with configurable limits: 3000 chars tables, 5000 chars text, 8000 chars combined

#### 3. Deterministic Classification from Web Content
- **Entry:** `src/class_extractor.py`
- Pattern-based classification that requires no LLM call (95% accuracy)
- Scans breadcrumbs, category labels, page titles, URL paths, and keyword density
- 90+ class aliases map abbreviations to canonical names (e.g., "shcs" -> "Socket Head Cap Screw")
- Parent-child specificity resolution (e.g., "Washer" demoted when "Split Lock Washer" also matches)
- Confidence threshold (score >= 4) before accepting a deterministic match
- Falls back to LLM classification only when pattern matching is inconclusive

#### 4. LLM Part Classification
- **Entry:** `src/part_classifier.py`
- Classifies part names into 81 categories using configurable LLM
- Batch classification: 100 parts per LLM call in Claude Code mode, 50 per call in API mode (75x faster than individual calls)
- Individual fallback for any parts that fail batch parsing
- LLM cache with 90-day TTL avoids re-classifying known parts

#### 5. Regex Pre-Extraction
- **Entry:** `src/regex_extractor.py`
- Pattern-based attribute extraction from scraped content before LLM call
- Extracts from: HTML tables (highest reliability), key-value patterns, standards (DIN, ASME, ISO), materials (18-8 SS, 304L, Carbon Steel, Viton, etc.)
- Builds label patterns dynamically from the ALIASES dictionary
- Agreement tracking: compares regex vs LLM results to measure confidence
- Pre-extracted values sent to LLM for validation, not as replacements

#### 6. LLM Attribute Extraction & Validation
- **Entry:** `src/attribute_extractor.py`
- Hybrid extraction prompt: schema attrs as priority hints + maximize coverage
- When regex pre-extracted values exist, LLM validates and fills gaps (not full extraction)
- Automatic unit conversion (inches <-> mm) per part's specified unit
- Validation retry: if >50% of schema attributes missing, targeted re-extraction for just the missing ones
- Temperature=0 for deterministic, reproducible output

#### 7. Canonical Attribute Normalization
- **Entry:** `src/attr_schema.py`
- Excel-based schema: `input/ClassificationSchema.xlsx` with 81 classes, 46 attributes, 169 aliases
- Fallback to hardcoded schemas if Excel file not found
- 500+ alias mappings normalize different naming conventions (e.g., "Screw Size", "Thread Size", "For Screw Size" all map to "Screw Size")
- DigiKey/Mouser API parameter names included in alias mappings
- Default schema for classes without specific definitions
- Fuzzy schema matching for partial class name matches

#### 8. Per-Class Excel Output
- **Entry:** `src/excel_handler.py`
- Groups parts by classified type
- Writes one `.xlsx` per class with consistent column headers
- TC Class ID column for Teamcenter integration
- Styled headers (blue fill, white bold), auto-sized columns
- Preserves original input columns + Part Class + Source URL + extracted attributes

### Execution Modes

#### 9. API Key CLI Mode (`main.py`)
- Single-threaded sequential processing with asyncio
- Configurable LLM provider via `.env` (8 providers supported)
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
- Batch classification: 100 parts per CLI call (75x faster)
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
- Bad-entry eviction: removes URLs that returned no useful content
- Cache-hit fast path skips search entirely
- Atomic writes for Windows safety
- Safe to commit (public URLs only)
- Coverage improves with each run as cache warms

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

#### 18. Windows UTF-8 Encoding Fix
- Forces UTF-8 encoding on Windows to prevent encoding errors in Excel output and console output
- Applied globally at startup

#### 19. Resume Capability
- **Entry:** `main.py` (progress.json), `main_cc.py` (progress_cc.json)
- Checkpoint saved after each part with full state
- Re-run to resume from last completed part
- Progress files deleted on successful completion

#### 20. 21 Production-Ready Bug Fixes
- Comprehensive hardening across all modules
- Edge case handling for malformed HTML, encoding issues, API timeouts
- Graceful degradation when optional dependencies are missing

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.11+ |
| LLM (Groq/OpenAI/Ollama) | OpenAI SDK | >= 1.40.0 |
| LLM (Anthropic/Bedrock) | Anthropic SDK | >= 0.40.0 |
| HTTP (TLS stealth) | curl_cffi | >= 0.7.0 |
| HTTP (async APIs) | httpx | >= 0.27.0 |
| HTML Parsing | BeautifulSoup4 | >= 4.12.0 |
| Stealth Browser | CloakBrowser | >= 0.3.0 (optional) |
| Excel I/O | openpyxl | >= 3.1.0 |
| Web UI | Streamlit | >= 1.38.0 |
| Env Config | python-dotenv | >= 1.0.0 |

## LLM Providers (8)

| Provider | Default Model | API Key Required | Notes |
|----------|--------------|------------------|-------|
| Groq | llama-3.3-70b-versatile | Yes (free) | Fastest inference, recommended to start |
| OpenAI | gpt-4o | Yes | GPT-4o, GPT-4-turbo, GPT-3.5-turbo |
| Anthropic | claude-sonnet-4-20250514 | Yes | Claude Opus, Sonnet, Haiku |
| Azure OpenAI | gpt-4o | Yes | Enterprise, requires AZURE_OPENAI_ENDPOINT |
| AWS Bedrock | anthropic.claude-sonnet-4-20250514-v1:0 | No (AWS creds) | Uses default AWS credential chain |
| Ollama | llama3.1 | No | Local inference, free, requires ollama serve |
| Custom | gpt-4o | Varies | Any OpenAI-compatible endpoint via LLM_BASE_URL |
| Claude Code CLI | (any backend) | No | Uses `claude` CLI on PATH, zero API keys |

## Roadmap

| Phase | Milestones | Status |
|-------|-----------|--------|
| v1.0 | Core pipeline: classify, scrape, extract, write Excel | Done |
| v1.1 | Multi-provider LLM support (7 providers), Streamlit web UI | Done |
| v1.2 | Distributor APIs (DigiKey, Mouser, McMaster) | Done |
| v1.3 | Claude Code CLI mode with batch + parallel workers | Done |
| v1.4 | CloakBrowser stealth scraping, manufacturer rotation | Done |
| v1.5 | Deterministic classification, regex pre-extraction, LLM cache, metrics | Done |
| v1.6 | Excel-based schema (81 classes), TC Class ID, hybrid prompts, 8th provider | Done |
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
│   ├── PartClassifierInput.xlsx       # Sample input (4 parts)
│   └── ClassificationSchema.xlsx      # Excel-based schema (81 classes, 46 attrs, 169 aliases)
├── output/                    # Generated Excel files (git-ignored)
├── docs/                      # HTML documentation pages
│   ├── index.html             # Documentation hub
│   ├── README.html            # Project overview landing page
│   ├── COO.html               # Strategy dashboard
│   ├── SITECONFIGURATIONS.html # Interactive setup guide
│   └── benchmark_report.html  # Benchmark results
└── src/
    ├── __init__.py
    ├── llm_client.py          # Unified async LLM client (8 providers)
    ├── claude_code_client.py  # Claude CLI wrapper (batch + parallel)
    ├── part_classifier.py     # LLM classification + batch (100/call)
    ├── web_scraper.py         # 7-tier content lookup with URL caching
    ├── stealth_scraper.py     # CloakBrowser integration
    ├── api_sources.py         # DigiKey/Mouser/McMaster APIs
    ├── attribute_extractor.py # Hybrid extraction + unit conversion + retry
    ├── class_extractor.py     # Deterministic class from web content (95% accuracy)
    ├── content_cleaner.py     # HTML table extraction + smart truncation
    ├── regex_extractor.py     # Pattern pre-extraction + agreement tracking
    ├── attr_schema.py         # Excel-based schema loader (81 classes, 500+ aliases)
    ├── llm_cache.py           # Thread-safe LLM response cache with TTL
    ├── metrics.py             # Run metrics tracker + history
    ├── shared.py              # Manufacturer rotation, cache I/O, atomic writes
    └── excel_handler.py       # Input reader + per-class output writer + TC Class ID
```
