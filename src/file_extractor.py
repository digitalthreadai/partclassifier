"""
File-based spec extraction (Tier 0 — runs BEFORE web/API search).

Looks for spec files in the /specs/ folder. Filename matching is substring-based
(case-insensitive) so the PN/MfgPN can appear anywhere in the filename:

  Priority 1 — both PN and MfgPN appear in the filename stem
  Priority 2 — only PN appears in the filename stem
  Priority 3 — only MfgPN appears in the filename stem

Examples that all match PN="12345" MfgPN="ABC-100":
  12345-ABC-100.pdf, ABC-100_datasheet.pdf, SPEC_12345_REV2.pdf,
  some_12345_ABC-100_v3.pdf

Supported extensions: .pdf, .png, .jpg, .jpeg, .webp

PDF strategy (cascading):
  1. Try pdfplumber for native text + tables
  2. If empty/sparse (< 100 chars) -> assume scanned PDF
  3. Render pages with PyMuPDF (fitz) and send to vision LLM

Image strategy: send directly to vision LLM via LLMClient.chat_vision().

File-extracted attributes are AUTHORITATIVE — they must not be overridden
by web/API extraction. main.py merges file_attrs LAST so they win.
"""

from pathlib import Path

from src.api_sources import SourceResult
from src.pdf_extractor import PDFExtractor

_SPECS_DIR = Path(__file__).parent.parent / "specs"
_PDF_EXTS = {".pdf"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_ALL_EXTS = _PDF_EXTS | _IMAGE_EXTS

# Below this many native-text chars, treat the PDF as scanned and use vision
_MIN_USEFUL_TEXT = 100

# Cap pages sent to vision LLM (avoid runaway cost on huge PDFs)
_MAX_VISION_PAGES = 5

# Quality thresholds for native text detection
_LOW_QUALITY_THRESHOLD = 0.4   # alnum ratio below this = likely garbled/scanned
_MIN_DISTINCT_TOKENS = 15      # fewer distinct words = likely not real text


def _text_quality_score(text: str) -> float:
    """Estimate extraction quality as ratio of alphanumeric chars to total non-whitespace.

    Returns 0.0-1.0. Low scores indicate garbled OCR artifacts or mostly symbols.
    """
    stripped = text.replace(" ", "").replace("\n", "")
    if not stripped:
        return 0.0
    alnum = sum(1 for c in stripped if c.isalnum())
    return alnum / len(stripped)


# ── File discovery ───────────────────────────────────────────────────────────

def find_spec_file(part_number: str, mfg_part_num: str) -> Path | None:
    """Locate a spec file in /specs/ by substring-matching the filename stem.

    Matching priority (all case-insensitive):
      1. Both PN and MfgPN appear anywhere in the stem
      2. Only PN appears anywhere in the stem
      3. Only MfgPN appears anywhere in the stem

    Returns the first match at the highest priority, or None if nothing found.
    Returns None if /specs/ folder doesn't exist or both PN and MfgPN are empty.
    """
    if not _SPECS_DIR.exists() or not _SPECS_DIR.is_dir():
        return None

    pn = (part_number or "").strip().lower()
    mfg = (mfg_part_num or "").strip().lower()
    if not pn and not mfg:
        return None

    # Collect all valid spec files with their lowercased stems
    candidates: list[tuple[Path, str]] = []
    for f in _SPECS_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in _ALL_EXTS:
            candidates.append((f, f.stem.lower()))

    # Priority 1: both PN and MfgPN appear in the stem
    if pn and mfg:
        for f, stem in candidates:
            if pn in stem and mfg in stem:
                print(f"    [File] Matched by PN+MfgPN: {f.name}")
                return f

    # Priority 2: only PN appears in the stem
    if pn:
        for f, stem in candidates:
            if pn in stem:
                print(f"    [File] Matched by PN: {f.name}")
                return f

    # Priority 3: only MfgPN appears in the stem
    if mfg:
        for f, stem in candidates:
            if mfg in stem:
                print(f"    [File] Matched by MfgPN: {f.name}")
                return f

    return None


# ── Public extraction API ────────────────────────────────────────────────────

async def extract_from_file(file_path: Path, llm) -> SourceResult | None:
    """Extract content from a spec file.

    PDFs cascade: pdfplumber -> fitz render -> vision LLM
    Images go straight to vision LLM.
    """
    ext = file_path.suffix.lower()
    if ext in _PDF_EXTS:
        return await _extract_pdf_smart(file_path, llm)
    if ext in _IMAGE_EXTS:
        return await _extract_image(file_path, llm)
    return None


# ── PDF extraction (cascading: native text -> vision fallback) ───────────────

async def _extract_pdf_smart(path: Path, llm) -> SourceResult | None:
    """Try native text extraction first; fall back to vision if sparse or low quality.

    Safety net: never returns None if native text was obtained (even if low quality),
    unless both native AND vision produced nothing.
    """
    # Step 1: pdfplumber (wrapped in try/except for corrupt PDFs)
    native_text = ""
    try:
        extractor = PDFExtractor()
        native_text = extractor.extract(str(path)) or ""
    except Exception as e:
        print(f"    [File] pdfplumber error: {e}")

    native_ok = (
        len(native_text.strip()) >= _MIN_USEFUL_TEXT
        and _text_quality_score(native_text) >= _LOW_QUALITY_THRESHOLD
        and len(set(native_text.split())) >= _MIN_DISTINCT_TOKENS
    )

    # Step 2: Good native text — use it directly
    if native_ok:
        print(f"    [File] Extracted {len(native_text)} chars (native text)")
        return SourceResult(
            content=native_text,
            source_url=f"file://{path.name}",
            source_name=f"file/{path.name}",
            method="native",
        )

    # Step 3: Sparse or low-quality native text — try vision LLM if supported
    quality = _text_quality_score(native_text) if native_text.strip() else 0.0
    if native_text.strip():
        print(f"    [File] Native text low quality (score={quality:.2f}, {len(native_text)} chars) — trying vision...")
    else:
        print(f"    [File] PDF appears to be scanned — trying vision LLM...")

    supports_vision = getattr(llm, "supports_vision", False)
    if supports_vision:
        vision_result = await _extract_pdf_via_vision(path, llm)
        if vision_result and vision_result.content and len(vision_result.content.strip()) >= 50:
            vision_result.method = "vision"
            return vision_result
        print(f"    [File] Vision extraction insufficient — falling back to native text")
    else:
        print(f"    [File] Vision not supported by this provider — skipping vision fallback")

    # Step 4: Safety net — return native text even if low quality (never discard usable content)
    if native_text.strip():
        print(f"    [File] Using low-quality native text as fallback ({len(native_text)} chars)")
        return SourceResult(
            content=native_text,
            source_url=f"file://{path.name}",
            source_name=f"file/{path.name}",
            method="native",
        )

    # Step 5: Both native and vision produced nothing
    print(f"    [File] No content extracted from PDF")
    return None


async def _extract_pdf_via_vision(path: Path, llm) -> SourceResult | None:
    """Render each PDF page to PNG via PyMuPDF and send to vision LLM."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"    [File] PyMuPDF not installed (pip install PyMuPDF)")
        return None

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        print(f"    [File] Failed to open PDF: {e}")
        return None

    page_count = min(len(doc), _MAX_VISION_PAGES)
    extracted_pages: list[str] = []

    for page_idx in range(page_count):
        try:
            page = doc.load_page(page_idx)
            # Render at 2x resolution for better OCR by vision LLM
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            png_bytes = pix.tobytes("png")
            text = await _vision_extract_image_bytes(png_bytes, "image/png", llm)
            if text:
                extracted_pages.append(f"[Page {page_idx + 1}]\n{text}")
        except Exception as e:
            print(f"    [File] Page {page_idx + 1} vision error: {e}")

    doc.close()

    if not extracted_pages:
        print(f"    [File] Vision extraction returned no content")
        return None

    full = "\n\n".join(extracted_pages)
    print(f"    [File] Extracted {len(full)} chars via vision ({len(extracted_pages)} pages)")
    return SourceResult(
        content=full,
        source_url=f"file://{path.name}",
        source_name=f"file/{path.name}",
        method="vision",
    )


# ── Image extraction (vision LLM) ────────────────────────────────────────────

async def _extract_image(path: Path, llm) -> SourceResult | None:
    """Send a standalone image file to vision LLM."""
    try:
        data = path.read_bytes()
    except Exception as e:
        print(f"    [File] Failed to read image: {e}")
        return None

    ext = path.suffix.lstrip(".").lower()
    if ext == "jpg":
        ext = "jpeg"
    media_type = f"image/{ext}"

    text = await _vision_extract_image_bytes(data, media_type, llm)
    if not text or len(text.strip()) < 50:
        print(f"    [File] Image vision extraction returned insufficient content")
        return None

    print(f"    [File] Extracted {len(text)} chars from image")
    return SourceResult(
        content=text,
        source_url=f"file://{path.name}",
        source_name=f"file/{path.name}",
        method="vision",
    )


# ── Shared vision LLM helper ─────────────────────────────────────────────────

_VISION_PROMPT = (
    "Extract ALL text and technical specifications from this image. "
    "Include any tables, dimensions, materials, standards, part numbers, "
    "tolerances, classifications. Preserve table structure with pipe (|) "
    "separators if applicable. Return as plain text only — no markdown."
)


async def _vision_extract_image_bytes(data: bytes, media_type: str, llm) -> str:
    """Send raw image bytes to a vision LLM and return extracted text.

    Provider-agnostic — delegates to LLMClient.chat_vision() which handles
    Anthropic vs OpenAI message format internally.
    """
    try:
        return await llm.chat_vision(
            prompt=_VISION_PROMPT,
            image_bytes=data,
            media_type=media_type,
            max_tokens=2000,
            temperature=0,
        )
    except Exception as e:
        print(f"    [File] Vision LLM error: {e}")
        return ""
