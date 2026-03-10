"""
Part Classification Agent -- Streamlit UI
=========================================
Run with:  streamlit run app.py
"""

import asyncio
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.llm_client import PROVIDER_PRESETS

# -- Paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"
DEFAULT_INPUT_DIR = str(BASE_DIR / "input")
OUTPUT_DIR = BASE_DIR / "output"

# -- Provider display names for the dropdown (derived from llm_client.py) ---
PROVIDER_DISPLAY = {
    preset["label"]: key for key, preset in PROVIDER_PRESETS.items()
}


# -- Helpers ---------------------------------------------------------------

def read_env() -> dict[str, str]:
    """Read the .env file into a dict."""
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def write_env(provider: str, api_key: str, model: str):
    """Write LLM config to .env file, preserving other variables."""
    env = read_env()
    env["LLM_PROVIDER"] = provider
    env["LLM_API_KEY"] = api_key
    env["LLM_MODEL"] = model
    env.pop("GROQ_API_KEY", None)  # Remove legacy key

    lines = [f"{k}={v}" for k, v in env.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n")

    # Update current process env so LLMClient picks it up
    os.environ["LLM_PROVIDER"] = provider
    os.environ["LLM_API_KEY"] = api_key
    os.environ["LLM_MODEL"] = model


def get_excel_files(folder: str) -> list[Path]:
    """Return all .xlsx files in a folder."""
    p = Path(folder)
    if not p.exists():
        return []
    return sorted(p.glob("*.xlsx"))


async def run_classification(input_path: str, output_dir: str, progress_callback=None):
    """Run the full classification pipeline, reporting progress via callback."""
    load_dotenv(ENV_PATH, override=True)

    from src.llm_client import LLMClient
    from src.excel_handler import ExcelHandler
    from src.part_classifier import PartClassifier
    from src.web_scraper import WebScraper
    from src.attribute_extractor import AttributeExtractor
    from main import process_part

    llm = LLMClient()
    handler = ExcelHandler(input_path, output_dir)
    classifier = PartClassifier(llm)
    attr_extractor = AttributeExtractor(llm)

    parts = handler.read_parts()
    total = len(parts)
    results = []

    if progress_callback:
        progress_callback("status", f"Processing {total} parts using {llm.display_name()}...")

    async with WebScraper() as scraper:
        for i, part in enumerate(parts):
            mfg_part_num = str(part.get("Manufacturer Part Number") or "").strip()
            part_name = str(part.get("Part Name") or "").strip()

            if progress_callback:
                progress_callback("progress", (i, total, mfg_part_num, part_name))

            result = await process_part(part, scraper, classifier, attr_extractor)
            results.append(result)

            if progress_callback:
                progress_callback("part_done", {
                    "index": i + 1,
                    "total": total,
                    "part_num": mfg_part_num,
                    "part_name": part_name,
                    "part_class": result["part_class"],
                    "source_url": result["source_url"] or "part name",
                    "attr_count": len(result["attributes"]),
                    "attributes": result["attributes"],
                })

    written = handler.write_class_files(results)
    return results, written


# -- Streamlit App ---------------------------------------------------------

st.set_page_config(
    page_title="Part Classification Agent",
    page_icon="&#9881;",
    layout="wide",
)

st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    div[data-testid="stSidebarContent"] { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)

# -- Sidebar: LLM Configuration -------------------------------------------

with st.sidebar:
    st.header("LLM Configuration")

    env = read_env()
    current_provider = env.get("LLM_PROVIDER", "").lower()
    current_key = env.get("LLM_API_KEY", env.get("GROQ_API_KEY", ""))
    current_model = env.get("LLM_MODEL", "")

    # Provider dropdown (labels from PROVIDER_PRESETS)
    provider_labels = list(PROVIDER_DISPLAY.keys())
    default_idx = 0
    for i, label in enumerate(provider_labels):
        if PROVIDER_DISPLAY[label] == current_provider:
            default_idx = i
            break

    selected_label = st.selectbox("Provider", provider_labels, index=default_idx)
    provider_key = PROVIDER_DISPLAY[selected_label]
    preset = PROVIDER_PRESETS[provider_key]

    # Model selection
    model_options = list(preset["models"])
    if current_model and current_model not in model_options:
        model_options = [current_model] + model_options
    default_model_idx = model_options.index(current_model) if current_model in model_options else 0
    selected_model = st.selectbox("Model", model_options, index=default_model_idx)

    # API Key
    if preset["needs_key"]:
        api_key_input = st.text_input(
            "API Key",
            value=current_key if current_provider == provider_key else "",
            type="password",
            help=f"Format: {preset['key_hint']}",
        )
        if preset["key_url"]:
            st.caption(f"[Get your API key]({preset['key_url']})")
    else:
        api_key_input = ""
        st.info("Ollama runs locally -- no API key needed.\nMake sure `ollama serve` is running.")

    # Save button
    if st.button("Save Configuration", type="primary", use_container_width=True):
        if preset["needs_key"] and not api_key_input.strip():
            st.error("API key is required for this provider.")
        else:
            write_env(provider_key, api_key_input.strip(), selected_model)
            st.success(f"Saved: {selected_model} via {selected_label}")
            st.rerun()

    # Status
    st.divider()
    configured = bool(
        env.get("LLM_PROVIDER") and env.get("LLM_API_KEY")
        or env.get("GROQ_API_KEY")
        or env.get("LLM_PROVIDER", "").lower() == "ollama"
    )
    if configured:
        st.success(f"Active: **{env.get('LLM_MODEL', preset['default_model'])}** via **{env.get('LLM_PROVIDER', 'groq')}**")
    else:
        st.warning("Not configured. Select a provider and save.")

# -- Main Area -------------------------------------------------------------

st.title("Part Classification Agent")
st.caption("Classify mechanical parts, scrape specifications, and generate structured Excel output.")

if not configured:
    st.info("Configure your LLM provider in the sidebar to get started.")
    st.stop()

st.divider()

# -- Input Section ---------------------------------------------------------
col1, col2 = st.columns([2, 1])

with col1:
    input_folder = st.text_input(
        "Input Folder",
        value=DEFAULT_INPUT_DIR,
        help="Folder containing .xlsx input files",
    )

with col2:
    output_folder = st.text_input(
        "Output Folder",
        value=str(OUTPUT_DIR),
        help="Folder where per-class output files will be written",
    )

excel_files = get_excel_files(input_folder)

if not excel_files:
    st.warning(f"No .xlsx files found in `{input_folder}`")
    st.stop()

selected_file = st.selectbox(
    "Select Input File",
    excel_files,
    format_func=lambda p: p.name,
)

# Preview input data
if selected_file:
    import openpyxl
    wb = openpyxl.load_workbook(str(selected_file))
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if any(row):
            rows.append(dict(zip(headers, row)))
    wb.close()

    st.markdown(f"**{len(rows)} parts found** in `{selected_file.name}`")

    with st.expander("Preview input data", expanded=False):
        st.dataframe(rows, use_container_width=True)

st.divider()

# -- Run Classification ----------------------------------------------------

if st.button("Run Classification", type="primary", use_container_width=True, disabled=not selected_file):
    progress_bar = st.progress(0)
    status_text = st.empty()
    part_results = []

    def progress_callback(event, data):
        if event == "status":
            status_text.info(data)
        elif event == "progress":
            i, total, part_num, part_name = data
            progress_bar.progress(int((i / total) * 100), text=f"Processing {i+1}/{total}: {part_num}")
        elif event == "part_done":
            part_results.append(data)
            progress_bar.progress(
                int((data["index"] / data["total"]) * 100),
                text=f"Completed {data['index']}/{data['total']}",
            )

    try:
        results, written_files = asyncio.run(
            run_classification(str(selected_file), output_folder, progress_callback)
        )

        progress_bar.progress(100, text="Complete!")
        status_text.empty()

        # -- Results Display -----------------------------------------------
        st.success(f"Classification complete! {len(results)} parts processed.")

        # Output files with download buttons
        st.subheader("Output Files")
        for f in written_files:
            fname = Path(f).name
            with open(f, "rb") as fh:
                st.download_button(
                    label=f"Download {fname}",
                    data=fh.read(),
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        # Per-part results
        st.subheader("Results Summary")
        for pr in part_results:
            with st.expander(
                f"{pr['part_num']} -- {pr['part_class']} ({pr['attr_count']} attributes)",
                expanded=False,
            ):
                c1, c2 = st.columns(2)
                c1.metric("Part Class", pr["part_class"])
                c2.metric("Attributes Found", pr["attr_count"])
                st.caption(f"Source: {pr['source_url']}")

                if pr["attributes"]:
                    st.table(
                        [{"Attribute": k, "Value": v} for k, v in pr["attributes"].items()]
                    )

    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Error: {e}")
        import traceback
        with st.expander("Full error details"):
            st.code(traceback.format_exc())
