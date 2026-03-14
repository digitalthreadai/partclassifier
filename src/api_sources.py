"""
Distributor API clients for structured part data.

Supported APIs:
  - DigiKey Product Information v4 (OAuth2, free tier)
  - Mouser Search API v2 (API key, free tier)
  - McMaster-Carr Product Information (mTLS, by request)

All APIs are optional. If credentials are not configured, the source is
silently skipped and the agent falls back to DuckDuckGo web scraping.
"""

import asyncio
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from src.attr_schema import normalize_attrs


# ── Shared result type ────────────────────────────────────────────────────────

@dataclass
class SourceResult:
    """Unified return type for all data sources (API and web scrape)."""
    content: str | None = None              # raw text for LLM extraction
    source_url: str | None = None           # citation URL
    attributes: dict[str, str] | None = None  # pre-extracted attrs (bypasses LLM)
    source_name: str = ""                   # e.g. "DigiKey API", "web"


# ── Unit conversion helper ────────────────────────────────────────────────────

_NUM_RE = re.compile(r"([-+]?\d*\.?\d+)\s*(mm|in|inch|inches|\")?", re.IGNORECASE)

def convert_dimension(value_str: str, target_unit: str) -> str:
    """Convert a dimensional value string to the target unit system.

    Non-dimensional values (e.g. 'Stainless Steel') pass through unchanged.
    """
    m = _NUM_RE.match(value_str.strip())
    if not m or not m.group(2):
        return value_str  # no unit detected, pass through

    number = float(m.group(1))
    src_unit = m.group(2).lower().rstrip("es").rstrip("ch")  # normalize "inches"→"in"
    if src_unit == '"':
        src_unit = "in"
    if src_unit == "m":  # "mm" without second m
        src_unit = "mm"

    want_mm = target_unit.lower().startswith("m")
    is_mm = src_unit == "mm"

    if want_mm and not is_mm:
        converted = number * 25.4
        return f"{converted:.3f} mm"
    elif not want_mm and is_mm:
        converted = number / 25.4
        return f"{converted:.4f} in"

    return value_str  # already in target unit


def _convert_attrs(attrs: dict[str, str], target_unit: str) -> dict[str, str]:
    """Apply unit conversion to all dimensional attribute values."""
    # Keys that typically hold dimensional values
    dim_keys = {
        "inner diameter", "outer diameter", "thickness", "length",
        "diameter", "width across flats", "head height", "head diameter",
        "height", "thread pitch",
    }
    result = {}
    for k, v in attrs.items():
        if k.lower() in dim_keys:
            result[k] = convert_dimension(v, target_unit)
        else:
            result[k] = v
    return result


# ── Abstract base ─────────────────────────────────────────────────────────────

class APISource(ABC):
    """Base class for distributor API integrations."""

    name: str = "Unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if credentials are configured."""

    @abstractmethod
    async def search(
        self, mfg_name: str, mfg_part_num: str, unit: str
    ) -> SourceResult | None:
        """Look up a part by manufacturer part number.

        Returns a SourceResult with structured attributes if found, or None.
        """


# ── DigiKey ───────────────────────────────────────────────────────────────────

class DigiKeyAPI(APISource):
    name = "DigiKey API"

    def __init__(self):
        self._client_id = os.getenv("DIGIKEY_CLIENT_ID", "").strip()
        self._client_secret = os.getenv("DIGIKEY_CLIENT_SECRET", "").strip()
        self._token: str | None = None
        self._token_expires_at: float = 0
        if self.is_available():
            print(f"  [API] DigiKey: configured")
        else:
            print(f"  [API] DigiKey: not configured (DIGIKEY_CLIENT_ID not set)")

    def is_available(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        """Get a valid OAuth2 token, refreshing if needed."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        resp = await client.post(
            "https://api.digikey.com/v1/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 1800)
        return self._token

    async def search(
        self, mfg_name: str, mfg_part_num: str, unit: str
    ) -> SourceResult | None:
        if not mfg_part_num:
            return None

        async with httpx.AsyncClient(timeout=30) as client:
            token = await self._ensure_token(client)
            headers = {
                "Authorization": f"Bearer {token}",
                "X-DIGIKEY-Client-Id": self._client_id,
                "Accept": "application/json",
            }

            # Search by keyword (manufacturer part number)
            resp = await client.get(
                f"https://api.digikey.com/products/v4/search/keyword",
                params={"keywords": mfg_part_num, "limit": 5},
                headers=headers,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            products = data.get("Products") or data.get("products") or []
            if not products:
                return None

            # Find best match — prefer exact manufacturer part number match
            product = products[0]
            for p in products:
                mpn = (p.get("ManufacturerPartNumber") or p.get("manufacturerPartNumber") or "")
                if mpn.lower() == mfg_part_num.lower():
                    product = p
                    break

            # Extract parameters into attribute dict
            params = product.get("Parameters") or product.get("parameters") or []
            attrs = {}
            for param in params:
                name = param.get("ParameterText") or param.get("parameterText") or ""
                value = param.get("ValueText") or param.get("valueText") or ""
                if name and value and value.lower() not in ("", "-", "n/a"):
                    attrs[name] = value

            # Build raw text fallback
            desc = product.get("DetailedDescription") or product.get("detailedDescription") or ""
            prod_desc = product.get("ProductDescription") or product.get("productDescription") or ""
            raw_parts = [f"Product: {prod_desc}", f"Description: {desc}"]
            for k, v in attrs.items():
                raw_parts.append(f"{k}: {v}")
            raw_text = "\n".join(raw_parts)

            source_url = (
                product.get("ProductUrl")
                or product.get("productUrl")
                or f"https://www.digikey.com/en/products/result?keywords={mfg_part_num}"
            )

            # Normalize attributes using the schema system
            # (part_class isn't known here, so we pass raw attrs;
            #  normalization happens later in the pipeline)
            converted = _convert_attrs(attrs, unit)

            return SourceResult(
                content=raw_text,
                source_url=source_url,
                attributes=converted if converted else None,
                source_name=self.name,
            )


# ── Mouser ────────────────────────────────────────────────────────────────────

class MouserAPI(APISource):
    name = "Mouser API"

    def __init__(self):
        self._api_key = os.getenv("MOUSER_API_KEY", "").strip()
        self._last_request: float = 0
        if self.is_available():
            print(f"  [API] Mouser: configured")
        else:
            print(f"  [API] Mouser: not configured (MOUSER_API_KEY not set)")

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def _throttle(self):
        """Respect Mouser's 30 req/min rate limit."""
        elapsed = time.time() - self._last_request
        if elapsed < 2.0:
            await asyncio.sleep(2.0 - elapsed)
        self._last_request = time.time()

    async def search(
        self, mfg_name: str, mfg_part_num: str, unit: str
    ) -> SourceResult | None:
        if not mfg_part_num:
            return None

        await self._throttle()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.mouser.com/api/v2/search/partnumber?apiKey={self._api_key}",
                json={
                    "SearchByPartRequest": {
                        "mouserPartNumber": mfg_part_num,
                        "partSearchOptions": "BeginsWith",
                    }
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            parts_list = (
                data.get("SearchResults", {}).get("Parts")
                or data.get("searchResults", {}).get("parts")
                or []
            )
            if not parts_list:
                return None

            part = parts_list[0]

            # Extract product attributes
            attrs = {}
            prod_attrs = (
                part.get("ProductAttributes") or part.get("productAttributes") or []
            )
            for attr in prod_attrs:
                name = attr.get("AttributeName") or attr.get("attributeName") or ""
                value = attr.get("AttributeValue") or attr.get("attributeValue") or ""
                if name and value and value.lower() not in ("", "-", "n/a"):
                    attrs[name] = value

            # Build raw text fallback
            desc = part.get("Description") or part.get("description") or ""
            raw_parts = [f"Product: {desc}"]
            for k, v in attrs.items():
                raw_parts.append(f"{k}: {v}")
            raw_text = "\n".join(raw_parts)

            source_url = (
                part.get("ProductDetailUrl")
                or part.get("productDetailUrl")
                or f"https://www.mouser.com/Search/Refine?Keyword={mfg_part_num}"
            )

            converted = _convert_attrs(attrs, unit)

            return SourceResult(
                content=raw_text,
                source_url=source_url,
                attributes=converted if converted else None,
                source_name=self.name,
            )


# ── McMaster-Carr ─────────────────────────────────────────────────────────────

class McMasterAPI(APISource):
    name = "McMaster API"

    def __init__(self):
        self._token = os.getenv("MCMASTER_BEARER_TOKEN", "").strip()
        self._cert_path = os.getenv("MCMASTER_CLIENT_CERT", "").strip()
        self._key_path = os.getenv("MCMASTER_CLIENT_KEY", "").strip()

        if self.is_available():
            print(f"  [API] McMaster: configured")
        else:
            print(f"  [API] McMaster: not configured (credentials not set)")

    def is_available(self) -> bool:
        if not (self._token and self._cert_path and self._key_path):
            return False
        # Verify cert files exist on disk
        return Path(self._cert_path).is_file() and Path(self._key_path).is_file()

    async def search(
        self, mfg_name: str, mfg_part_num: str, unit: str
    ) -> SourceResult | None:
        if not mfg_part_num:
            return None

        cert = (self._cert_path, self._key_path)
        async with httpx.AsyncClient(timeout=30, cert=cert) as client:
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            }

            # McMaster requires subscribing to a part before querying it
            await client.put(
                f"https://api.mcmaster.com/v1/products",
                json={"partNumbers": [mfg_part_num]},
                headers=headers,
            )

            resp = await client.get(
                f"https://api.mcmaster.com/v1/products/{mfg_part_num}",
                headers=headers,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()

            # Extract specifications
            attrs = {}
            specs = data.get("specifications") or data.get("Specifications") or {}
            if isinstance(specs, dict):
                attrs = {k: str(v) for k, v in specs.items() if v}
            elif isinstance(specs, list):
                for spec in specs:
                    name = spec.get("name") or spec.get("Name") or ""
                    value = spec.get("value") or spec.get("Value") or ""
                    if name and value:
                        attrs[name] = str(value)

            desc = data.get("description") or data.get("Description") or ""
            raw_parts = [f"Product: {desc}"]
            for k, v in attrs.items():
                raw_parts.append(f"{k}: {v}")
            raw_text = "\n".join(raw_parts)

            source_url = f"https://www.mcmaster.com/{mfg_part_num}"

            converted = _convert_attrs(attrs, unit)

            return SourceResult(
                content=raw_text,
                source_url=source_url,
                attributes=converted if converted else None,
                source_name=self.name,
            )


# ── Factory ───────────────────────────────────────────────────────────────────

def get_api_sources() -> list[APISource]:
    """Instantiate all API sources and return only those with valid credentials."""
    all_sources = [DigiKeyAPI(), MouserAPI(), McMasterAPI()]
    return [s for s in all_sources if s.is_available()]
