"""
Web scraper using curl_cffi (real browser TLS fingerprint) + DuckDuckGo search.
Strategy: search for the MFG part number, scrape the best result page.
No Playwright needed — curl_cffi handles bot-detection at the TLS level.

Distributor APIs (DigiKey, Mouser, McMaster) are tried first when configured.
Falls back to DuckDuckGo web scraping if no API returns sufficient data.
"""

import urllib.parse
import re
import json
import time
from pathlib import Path
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

from src.api_sources import SourceResult, get_api_sources

# Optional stealth browser for bot-protected sites (McMaster-Carr, etc.)
try:
    from src.stealth_scraper import StealthScraper, stealth_available
    _HAS_STEALTH = stealth_available()
except ImportError:
    _HAS_STEALTH = False

MIN_USEFUL_CHARS = 400
MAX_CONTENT_CHARS = 10_000

# Cache file — maps mfg_part_num -> best source URL found on a previous run
_CACHE_PATH = Path(__file__).parent.parent / "url_cache.json"

def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except Exception:
            pass
    return {}

def _save_cache(cache: dict) -> None:
    _CACHE_PATH.write_text(json.dumps(cache, indent=2))

# Skip domains that won't have useful specs
SKIP_DOMAINS = {
    "youtube.com", "amazon.com", "ebay.com", "alibaba.com",
    "twitter.com", "facebook.com", "linkedin.com", "reddit.com",
    "wikipedia.org", "pinterest.com",
}


class WebScraper:
    def __init__(self):
        self._session = cffi_requests.Session(impersonate="chrome124")
        self._cache = _load_cache()
        self._api_sources = get_api_sources()
        self._stealth: StealthScraper | None = None
        if _HAS_STEALTH:
            print("  [Stealth] CloakBrowser available (will launch on first use)")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self._session.close()
        if self._stealth:
            await self._stealth.close()

    async def _ensure_stealth(self) -> StealthScraper | None:
        """Lazily launch the stealth browser on first use."""
        if not _HAS_STEALTH:
            return None
        if self._stealth is None:
            self._stealth = StealthScraper()
            await self._stealth.launch()
        return self._stealth

    # ── Public API ────────────────────────────────────────────────────────────

    async def find_and_scrape(self, mfg_name: str, mfg_part_num: str, unit: str = "") -> SourceResult:
        """
        Look up a part: try distributor APIs first, then DuckDuckGo web scraping.
        Returns a SourceResult with structured attributes and/or raw text.
        """
        # --- Try API sources first ---
        for source in self._api_sources:
            try:
                result = await source.search(mfg_name, mfg_part_num, unit)
                if result and result.attributes and len(result.attributes) >= 3:
                    print(f"    Source ({result.source_name}): {result.source_url}")
                    self._cache[mfg_part_num] = result.source_url
                    _save_cache(self._cache)
                    return result
            except Exception as e:
                print(f"    {source.name} error: {e}")

        # --- Try stealth browser for manufacturers with known direct URLs ---
        if _HAS_STEALTH:
            direct_url = _direct_part_url(mfg_name, mfg_part_num)
            if direct_url:
                stealth = await self._ensure_stealth()
                if stealth:
                    result = await stealth.scrape_direct_url(direct_url, label=mfg_name)
                    if result and result.content and len(result.content) >= MIN_USEFUL_CHARS:
                        print(f"    Source (stealth/{mfg_name}): {result.source_url}")
                        self._cache[mfg_part_num] = result.source_url
                        _save_cache(self._cache)
                        return result
                    else:
                        print(f"    Stealth direct scrape insufficient, continuing...")

        # --- Cache hit: reuse previously found URL ---
        if mfg_part_num in self._cache:
            cached_url = self._cache[mfg_part_num]
            content = self._scrape_url(cached_url)
            if content and len(content) >= MIN_USEFUL_CHARS:
                print(f"    Source (cached): {cached_url}")
                return SourceResult(content=content, source_url=cached_url, source_name="web")
            else:
                # Cached URL is dead — remove and re-search
                print(f"    Cached URL failed, re-searching...")
                del self._cache[mfg_part_num]

        # --- Search and score all candidates ---
        queries = _build_queries(mfg_name, mfg_part_num, unit)

        all_urls: list[str] = []
        seen: set[str] = set()
        for query in queries:
            for url in self._search_duckduckgo(query):
                if url not in seen:
                    all_urls.append(url)
                    seen.add(url)
            time.sleep(1.5)  # avoid DuckDuckGo rate-limiting between queries

        # Sort: preferred trusted domains first
        preferred = [u for u in all_urls if _is_preferred(u)]
        others    = [u for u in all_urls if not _is_preferred(u)]

        best_content: str | None = None
        best_url:     str | None = None
        best_score:   int        = 0

        for url in preferred + others:
            content = self._scrape_url(url)
            if not content or len(content) < MIN_USEFUL_CHARS:
                continue
            score = _spec_score(content, mfg_part_num)
            # Short-circuit on a trusted hit with solid score
            if _is_preferred(url) and score >= 3:
                self._cache[mfg_part_num] = url
                _save_cache(self._cache)
                print(f"    Source (trusted): {url}  [score={score}]")
                return SourceResult(content=content, source_url=url, source_name="web")
            if score > best_score:
                best_score, best_content, best_url = score, content, url

        if best_url:
            self._cache[mfg_part_num] = best_url
            _save_cache(self._cache)
            reliability = "(trusted)" if _is_preferred(best_url) else "(unverified)"
            print(f"    Source {reliability}: {best_url}  [score={best_score}]")
            return SourceResult(content=best_content, source_url=best_url, source_name="web")

        # --- Stealth fallback: search + scrape via browser when curl_cffi found nothing ---
        if _HAS_STEALTH:
            stealth = await self._ensure_stealth()
            if stealth:
                query = f"{mfg_name} {mfg_part_num} specifications"
                result = await stealth.search_and_scrape(query, mfg_name=mfg_name)
                if result and result.content and len(result.content) >= MIN_USEFUL_CHARS:
                    print(f"    Source (stealth/{mfg_name}): {result.source_url}")
                    self._cache[mfg_part_num] = result.source_url
                    _save_cache(self._cache)
                    return result

        return SourceResult(source_name="none")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _search_duckduckgo(self, query: str) -> list[str]:
        """Return top result URLs from DuckDuckGo HTML search."""
        try:
            resp = self._session.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"Accept-Language": "en-US,en;q=0.9"},
                timeout=15,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            urls = []
            for a in soup.select(".result__a"):
                href = a.get("href", "")
                url = _extract_ddg_url(href)
                if url and not _skip_url(url):
                    urls.append(url)
            return urls[:5]
        except Exception as e:
            print(f"    Search error: {e}")
            return []

    def _scrape_url(self, url: str) -> str | None:
        """Fetch a URL and return cleaned plain text."""
        try:
            resp = self._session.get(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=15,
                allow_redirects=True,
            )
            if resp.status_code >= 400:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                              "aside", "iframe", "form"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            # Collapse excessive blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:MAX_CONTENT_CHARS] if text else None

        except Exception as e:
            print(f"    Scrape error ({url[:60]}): {e}")
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────

# Manufacturers with known direct part URL patterns.
# Add new entries as you discover them — the stealth browser will navigate directly.
DIRECT_URL_PATTERNS: dict[str, str] = {
    "mcmaster": "https://www.mcmaster.com/{part}",
    "fastenal": "https://www.fastenal.com/product/{part}",
    "grainger": "https://www.grainger.com/search?searchQuery={part}",
}


def _direct_part_url(mfg_name: str, part_number: str) -> str | None:
    """Return a direct URL for a manufacturer, or None if not mapped."""
    name_lower = mfg_name.lower()
    for key, pattern in DIRECT_URL_PATTERNS.items():
        if key in name_lower:
            return pattern.format(part=part_number)
    return None


def _build_queries(mfg_name: str, mfg_part_num: str, unit: str = "") -> list[str]:
    """Return ordered list of search queries to try, preferring the requested unit system."""
    unit_hint = "mm" if unit.lower() == "mm" else "inches" if unit.lower() == "inches" else ""
    is_mcmaster = "mcmaster" in mfg_name.lower()

    queries: list[str] = []

    if is_mcmaster:
        queries += [
            f"skdin {mfg_part_num}",                                           # targets skdin.com directly
            f"McMaster {mfg_part_num} specifications {unit_hint}".strip(),
            f"McMaster {mfg_part_num} dimensions {unit_hint}".strip(),
        ]
    else:
        queries += [
            f"{mfg_name} {mfg_part_num} specifications {unit_hint}".strip(),
        ]

    queries += [
        f"{mfg_part_num} specifications {unit_hint}".strip(),
        f'"{mfg_part_num}" dimensions datasheet',
    ]
    return queries


# Domains known to have reliable industrial fastener spec data
PREFERRED_DOMAINS = {
    "skdin.com",
    "olander.com",
    "aftfasteners.com",
    "aspenfasteners.com",
    "boltdepot.com",
    "albanycountyfasteners.com",
    "fastenal.com",
    "zoro.com",
    "lily-bearing.com",
}


def _extract_ddg_url(href: str) -> str | None:
    """Extract the real URL from a DuckDuckGo redirect href."""
    if not href:
        return None
    # DuckDuckGo HTML wraps links: /l/?uddg=<encoded_url>&...
    if "uddg=" in href:
        try:
            encoded = re.search(r"uddg=([^&]+)", href).group(1)
            return urllib.parse.unquote(encoded)
        except Exception:
            return None
    if href.startswith("http"):
        return href
    return None


SPEC_KEYWORDS = [
    "inner diameter", "outer diameter", "thickness", "material",
    "hardness", "standard", "din", "asme", "iso", "ansi",
    "stainless", "washer", "screw size", "specifications",
]

def _spec_score(content: str, part_num: str) -> int:
    """Score content by spec-keyword density. Higher = richer spec data."""
    lower = content.lower()
    score = sum(1 for kw in SPEC_KEYWORDS if kw in lower)
    # Bonus if the exact part number appears in the content
    if part_num.lower() in lower:
        score += 3
    return score


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_preferred(url: str) -> bool:
    d = _domain(url)
    return any(p in d for p in PREFERRED_DOMAINS)


def _skip_url(url: str) -> bool:
    """Return True if the URL should be skipped."""
    try:
        domain = urllib.parse.urlparse(url).netloc.lower()
        return any(skip in domain for skip in SKIP_DOMAINS)
    except Exception:
        return False
