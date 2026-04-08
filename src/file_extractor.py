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
    """Try native text extraction first. If empty/sparse, fall back to vision."""
    # Step 1: pdfplumber (handles native text + tables)
    extractor = PDFExtractor()
    text = extractor.extract(str(path))

    if text and len(text.strip()) >= _MIN_USEFUL_TEXT:
        # Native text PDF — done
        print(f"    [File] Extracted {len(text)} chars (native text)")
        return SourceResult(
            content=text,
            source_url=f"file://{path.name}",
            source_name=f"file/{path.name}",
        )

    # Step 2: Scanned PDF — render pages and use vision
    print(f"    [File] PDF appears to be scanned, using vision LLM...")
    return await _extract_pdf_via_vision(path, llm)


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
