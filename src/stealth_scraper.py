"""
Stealth browser scraper using CloakBrowser for JS-heavy / bot-protected sites.

CloakBrowser is a custom-compiled Chromium with source-level patches that bypass
bot detection (Cloudflare, reCAPTCHA, FingerprintJS, etc.).

This module is optional — if cloakbrowser is not installed, stealth_available()
returns False and the rest of the codebase falls back to curl_cffi.
"""

import asyncio
import os
import random
import re

from src.api_sources import SourceResult

MAX_CONTENT_CHARS = 10_000


def stealth_available() -> bool:
    """Return True if cloakbrowser is installed and not disabled via env var."""
    if os.getenv("STEALTH_BROWSER_ENABLED", "true").lower() in ("false", "0", "no"):
        return False
    try:
        import cloakbrowser  # noqa: F401
        return True
    except ImportError:
        return False


class StealthScraper:
    """Browser-based scraper using CloakBrowser for bot-protected sites."""

    def __init__(self):
        self._browser = None

    async def launch(self) -> None:
        """Launch the stealth Chromium browser (reused across scrapes)."""
        if self._browser:
            return
        from cloakbrowser import launch_async
        self._browser = await launch_async(headless=True, humanize=True)
        print("  [Stealth] CloakBrowser launched")

    async def close(self) -> None:
        """Close the browser if running."""
        if self._browser:
            await self._browser.close()
            self._browser = None

    async def scrape_direct_url(self, url: str, label: str = "") -> SourceResult | None:
        """Navigate directly to a manufacturer URL and extract spec text.

        Works for any site that serves a JS-only SPA (McMaster, etc.).
        We wait for the page to hydrate, then extract all text from the main
        content area (avoiding brittle CSS selectors).

        Returns SourceResult on success, None if blocked or empty.
        """
        if not self._browser:
            return None

        # Fresh browser context per scrape — clean cookies, localStorage, session
        # This prevents McMaster from tracking across multiple page loads
        context = await self._browser.new_context()
        page = await context.new_page()
        tag = f"[Stealth/{label}]" if label else "[Stealth]"
        try:
            # Random delay to simulate human arriving at the page
            await asyncio.sleep(random.uniform(2, 5))

            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Extra buffer for SPA hydration
            await asyncio.sleep(random.uniform(2, 4))

            # Extract all visible text from the page body
            text = await page.evaluate("""() => {
                // Remove non-content elements
                const removeTags = ['script', 'style', 'noscript', 'nav',
                                    'header', 'footer', 'iframe'];
                removeTags.forEach(tag => {
                    document.querySelectorAll(tag).forEach(el => el.remove());
                });

                // Get all text from the body
                const body = document.body;
                if (!body) return '';

                // Try to find spec/detail content areas first
                const selectors = [
                    '[class*="spec"]', '[class*="detail"]', '[class*="product"]',
                    '[class*="attribute"]', '[class*="param"]', '[data-testid]',
                    'table', 'dl', '.content', 'main', 'article'
                ];

                let texts = [];
                for (const sel of selectors) {
                    document.querySelectorAll(sel).forEach(el => {
                        const t = el.innerText?.trim();
                        if (t && t.length > 20) texts.push(t);
                    });
                }

                // Fallback: grab everything from body
                if (texts.length === 0) {
                    texts.push(body.innerText || '');
                }

                return [...new Set(texts)].join('\\n\\n');
            }""")

            if not text or len(text.strip()) < 100:
                print(f"    {tag} page returned insufficient content ({len(text or '')} chars)")
                return None

            # Clean up the text
            text = re.sub(r"\n{3,}", "\n\n", text.strip())
            text = text[:MAX_CONTENT_CHARS]

            print(f"    {tag} extracted {len(text)} chars")
            return SourceResult(
                content=text,
                source_url=url,
                source_name=f"CloakBrowser/{label}" if label else "CloakBrowser",
            )

        except Exception as e:
            print(f"    {tag} scrape error: {e}")
            return None
        finally:
            await page.close()
            await context.close()

    async def search_and_scrape(self, query: str, mfg_name: str = "") -> SourceResult | None:
        """Search DuckDuckGo via the stealth browser and scrape the best result.

        Uses the browser for both the search and the result page, so it works
        even when DuckDuckGo or the target site blocks curl_cffi.

        Returns SourceResult on success, None if nothing useful found.
        """
        if not self._browser:
            return None

        page = await self._browser.new_page()
        label = mfg_name or "web"
        try:
            await asyncio.sleep(random.uniform(1, 3))

            # Search DuckDuckGo
            search_url = f"https://duckduckgo.com/?q={query}"
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(1, 2))

            # Extract result URLs from DuckDuckGo
            urls = await page.evaluate("""() => {
                const links = document.querySelectorAll('a[data-testid="result-title-a"], .result__a');
                return Array.from(links).map(a => a.href).filter(h => h.startsWith('http')).slice(0, 5);
            }""")

            await page.close()

            if not urls:
                print(f"    [Stealth] No search results for: {query[:50]}")
                return None

            # Try each result URL
            for url in urls:
                content = await self.scrape_url(url)
                if content and len(content) >= 400:
                    print(f"    [Stealth/{label}] Got {len(content)} chars from {url[:60]}")
                    return SourceResult(
                        content=content,
                        source_url=url,
                        source_name=f"CloakBrowser/{label}",
                    )

            return None

        except Exception as e:
            print(f"    [Stealth] Search error: {e}")
            if not page.is_closed():
                await page.close()
            return None

    async def scrape_url(self, url: str) -> str | None:
        """Scrape any URL using the stealth browser (JS rendering + bot bypass).

        Used as a fallback when curl_cffi can't get enough content.
        Returns cleaned text or None.
        """
        if not self._browser:
            return None

        page = await self._browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1)

            text = await page.evaluate("""() => {
                ['script', 'style', 'noscript', 'nav', 'header', 'footer',
                 'iframe', 'aside', 'form'].forEach(tag => {
                    document.querySelectorAll(tag).forEach(el => el.remove());
                });
                return document.body ? document.body.innerText : '';
            }""")

            if not text:
                return None

            text = re.sub(r"\n{3,}", "\n\n", text.strip())
            return text[:MAX_CONTENT_CHARS] if text else None

        except Exception as e:
            print(f"    [Stealth] Scrape error ({url[:60]}): {e}")
            return None
        finally:
            await page.close()
