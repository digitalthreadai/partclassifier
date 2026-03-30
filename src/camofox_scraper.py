"""
CamoFox stealth browser — Firefox-based anti-detection via REST API.

CamoFox wraps Camoufox (a Firefox fork with C++-level fingerprint spoofing)
behind a REST API server. Unlike Chromium-based stealth browsers, Firefox uses
Juggler protocol and a completely different fingerprint surface, providing an
independent evasion vector for sites that block Chromium headless browsers.

Requires: CamoFox server running (Docker or npm start).
  docker run -p 3000:3000 ghcr.io/jo-inc/camofox-browser
  OR: npm install @askjo/camofox-browser && npm start

Configuration:
  CAMOFOX_URL=http://localhost:3000  (server address)
  CAMOFOX_API_KEY=                   (optional, for authenticated endpoints)

This module is optional — if CamoFox is not running, camofox_available()
returns False and the pipeline falls back to CloakBrowser or curl_cffi.
"""

import asyncio
import os
import random
import re
from urllib.parse import quote_plus

import httpx

from src.api_sources import SourceResult

MAX_CONTENT_CHARS = 10_000
_DEFAULT_URL = "http://localhost:3000"


def camofox_available() -> bool:
    """Check if CamoFox server is running and reachable.

    Returns False if STEALTH_ENGINE explicitly excludes CamoFox,
    or if the server is not responding at CAMOFOX_URL.
    """
    engine = os.getenv("STEALTH_ENGINE", "auto").lower()
    if engine in ("cloakbrowser", "none"):
        return False
    base = os.getenv("CAMOFOX_URL", _DEFAULT_URL)
    try:
        resp = httpx.get(f"{base}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


class CamoFoxScraper:
    """Stealth scraper using CamoFox REST API (Firefox-based anti-detection).

    Same interface as StealthScraper (CloakBrowser) — drop-in replacement.
    Uses httpx async client for all API calls.
    """

    def __init__(self):
        self._base = os.getenv("CAMOFOX_URL", _DEFAULT_URL)
        self._api_key = os.getenv("CAMOFOX_API_KEY", "")
        self._client: httpx.AsyncClient | None = None
        self._session_key = f"partclassifier-{os.getpid()}"

    async def launch(self) -> None:
        """Initialize async HTTP client. CamoFox server must already be running."""
        if self._client:
            return
        headers = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers=headers,
            timeout=45,
        )
        print("  [CamoFox] Connected to server")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Core scraping methods (same interface as StealthScraper) ──────────

    async def scrape_direct_url(self, url: str, label: str = "") -> SourceResult | None:
        """Navigate directly to a URL via CamoFox and extract content.

        Uses CamoFox accessibility snapshot for compact, structured text
        extraction (~90% smaller than raw HTML).
        """
        if not self._client:
            return None

        tag = f"[CamoFox/{label}]" if label else "[CamoFox]"
        tab_id = None

        try:
            # Random delay to simulate human arrival
            await asyncio.sleep(random.uniform(1, 3))

            # Create tab
            resp = await self._client.post("/tabs", json={
                "sessionKey": self._session_key,
            })
            if resp.status_code != 200:
                return None
            tab_id = resp.json().get("tabId")

            # Navigate to URL
            resp = await self._client.post(f"/tabs/{tab_id}/navigate", json={
                "url": url,
                "waitUntil": "networkidle",
            })
            if resp.status_code != 200:
                return None

            # Extra wait for SPA hydration
            await asyncio.sleep(random.uniform(2, 4))

            # Take accessibility snapshot (compact text, no HTML noise)
            text = await self._get_snapshot(tab_id)

            if not text or len(text.strip()) < 100:
                print(f"    {tag} page returned insufficient content ({len(text or '')} chars)")
                return None

            # Clean up
            text = re.sub(r"\n{3,}", "\n\n", text.strip())
            text = text[:MAX_CONTENT_CHARS]

            print(f"    {tag} extracted {len(text)} chars")
            return SourceResult(
                content=text,
                source_url=url,
                source_name=f"CamoFox/{label}" if label else "CamoFox",
            )

        except httpx.TimeoutException:
            print(f"    {tag} timeout navigating to {url[:60]}")
            return None
        except Exception as e:
            print(f"    {tag} scrape error: {e}")
            return None
        finally:
            if tab_id:
                await self._close_tab(tab_id)

    async def search_and_scrape(self, query: str, mfg_name: str = "") -> SourceResult | None:
        """Search DuckDuckGo via CamoFox and scrape the best result.

        Uses the browser for both search and result pages, bypassing
        bot detection on both sides.
        """
        if not self._client:
            return None

        label = mfg_name or "web"
        tab_id = None

        try:
            await asyncio.sleep(random.uniform(2, 4))

            # Create tab for search
            resp = await self._client.post("/tabs", json={
                "sessionKey": self._session_key,
            })
            if resp.status_code != 200:
                return None
            tab_id = resp.json().get("tabId")

            # Navigate to DuckDuckGo search
            search_url = f"https://duckduckgo.com/?q={quote_plus(query)}"
            resp = await self._client.post(f"/tabs/{tab_id}/navigate", json={
                "url": search_url,
                "waitUntil": "networkidle",
            })
            if resp.status_code != 200:
                return None

            await asyncio.sleep(random.uniform(1, 2))

            # Extract search result links from snapshot
            snapshot = await self._get_snapshot(tab_id)
            urls = self._extract_urls_from_snapshot(snapshot)

            # Close search tab
            await self._close_tab(tab_id)
            tab_id = None

            if not urls:
                print(f"    [CamoFox] No search results for: {query[:50]}")
                return None

            # Try each result URL
            for result_url in urls[:5]:
                content = await self.scrape_url(result_url)
                if content and len(content) >= 400:
                    print(f"    [CamoFox/{label}] Got {len(content)} chars from {result_url[:60]}")
                    return SourceResult(
                        content=content,
                        source_url=result_url,
                        source_name=f"CamoFox/{label}",
                    )

            return None

        except Exception as e:
            print(f"    [CamoFox] Search error: {e}")
            return None
        finally:
            if tab_id:
                await self._close_tab(tab_id)

    async def scrape_url(self, url: str) -> str | None:
        """Scrape any URL using CamoFox (Firefox rendering + anti-detection).

        Returns cleaned text or None.
        """
        if not self._client:
            return None

        tab_id = None
        try:
            # Create tab
            resp = await self._client.post("/tabs", json={
                "sessionKey": self._session_key,
            })
            if resp.status_code != 200:
                return None
            tab_id = resp.json().get("tabId")

            # Navigate
            resp = await self._client.post(f"/tabs/{tab_id}/navigate", json={
                "url": url,
                "waitUntil": "networkidle",
            })
            if resp.status_code != 200:
                return None

            await asyncio.sleep(1)

            # Get snapshot
            text = await self._get_snapshot(tab_id)
            if not text:
                return None

            text = re.sub(r"\n{3,}", "\n\n", text.strip())
            return text[:MAX_CONTENT_CHARS] if text else None

        except httpx.TimeoutException:
            return None
        except Exception as e:
            print(f"    [CamoFox] Scrape error ({url[:60]}): {e}")
            return None
        finally:
            if tab_id:
                await self._close_tab(tab_id)

    # ── Private helpers ──────────────────────────────────────────────────

    async def _get_snapshot(self, tab_id: str) -> str:
        """Get accessibility tree snapshot from CamoFox (compact text).

        Falls back to extracting links/text content if snapshot fails.
        """
        try:
            resp = await self._client.post(f"/tabs/{tab_id}/snapshot")
            if resp.status_code == 200:
                data = resp.json()
                # Snapshot returns structured accessibility tree text
                return data.get("snapshot", data.get("text", ""))
        except Exception:
            pass

        # Fallback: extract content via /content endpoint
        try:
            resp = await self._client.post(f"/tabs/{tab_id}/content", json={
                "extractText": True,
            })
            if resp.status_code == 200:
                data = resp.json()
                return data.get("text", "")
        except Exception:
            pass

        return ""

    async def _close_tab(self, tab_id: str) -> None:
        """Close a CamoFox tab (cleanup)."""
        try:
            await self._client.delete(f"/tabs/{tab_id}")
        except Exception:
            pass

    @staticmethod
    def _extract_urls_from_snapshot(snapshot: str) -> list[str]:
        """Extract HTTP URLs from a snapshot/text block (search results)."""
        if not snapshot:
            return []
        # Match URLs that look like search results (not DuckDuckGo internal)
        urls = re.findall(r'https?://[^\s<>"\')\]]+', snapshot)
        # Filter out search engine URLs
        skip = {"duckduckgo.com", "google.com", "bing.com", "yahoo.com"}
        filtered = []
        seen = set()
        for url in urls:
            # Clean trailing punctuation
            url = url.rstrip(".,;:")
            domain = url.split("/")[2] if len(url.split("/")) > 2 else ""
            if domain and not any(s in domain for s in skip) and url not in seen:
                seen.add(url)
                filtered.append(url)
        return filtered
