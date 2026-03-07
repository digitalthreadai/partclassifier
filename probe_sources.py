"""
Probe whether Grainger, Zoro, and MSC Direct carry our test McMaster parts
and whether their pages have the dimensional spec data we need.
"""
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

PARTS = [
    ("92148A261", "M20 split lock washer"),
    ("92148A112", "M27 split lock washer"),
    ("98449A515",  "#5 internal tooth lock washer"),
]

SOURCES = {
    "Grainger": "https://www.grainger.com/search?searchQuery={part}",
    "Zoro":     "https://www.zoro.com/search?q={part}",
    "MSC":      "https://www.mscdirect.com/search/results?searchterm={part}",
}

SPEC_KEYWORDS = ["Inner Diameter", "Outer Diameter", "Thickness", "DIN", "ASME",
                 "Material", "Hardness", "21.2", "27.5", "0.136", "Stainless"]

session = cffi_requests.Session(impersonate="chrome124")

for part, desc in PARTS:
    print(f"\n{'='*60}")
    print(f"Part: {part} ({desc})")
    for name, url_template in SOURCES.items():
        url = url_template.format(part=part)
        try:
            r = session.get(url, timeout=15, headers={"Accept-Language": "en-US,en;q=0.9"})
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style"]): tag.decompose()
            text = soup.get_text(" ", strip=True)
            hits = [kw for kw in SPEC_KEYWORDS if kw.lower() in text.lower()]
            print(f"  {name:10} status={r.status_code} len={len(text):6,}  keywords={hits}")
        except Exception as e:
            print(f"  {name:10} ERROR: {e}")

session.close()
