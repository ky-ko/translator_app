import hashlib
import logging
import os
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
from translator import translate_docx

log = logging.getLogger("translator")

STATIC_DIR = "/app/static"
CACHE_TTL = 24 * 3600  # seconds


def _write_docx(key: str, docx_bytes: bytes) -> None:
    os.makedirs(STATIC_DIR, exist_ok=True)
    with open(os.path.join(STATIC_DIR, f"{key}.docx"), "wb") as f:
        f.write(docx_bytes)


def _write_txt(key: str, txt: str) -> None:
    os.makedirs(STATIC_DIR, exist_ok=True)
    with open(os.path.join(STATIC_DIR, f"{key}.txt"), "w", encoding="utf-8") as f:
        f.write(txt)


def _ensure_zip(results: dict) -> str:
    """Write a ZIP directly to disk (streaming, no full-file RAM buffer). Returns filename."""
    zip_key = hashlib.sha256("|".join(sorted(results.values())).encode()).hexdigest()
    zip_path = os.path.join(STATIC_DIR, f"{zip_key}.zip")
    if not os.path.exists(zip_path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, key in results.items():
                base = filename.replace(".docx", "_en")
                zf.write(os.path.join(STATIC_DIR, f"{key}.docx"), arcname=f"{base}.docx")
                zf.write(os.path.join(STATIC_DIR, f"{key}.txt"), arcname=f"{base}.txt")
    return f"{zip_key}.zip"


def _cleanup_cache() -> None:
    if not os.path.isdir(STATIC_DIR):
        return
    now = time.time()
    for fname in os.listdir(STATIC_DIR):
        fpath = os.path.join(STATIC_DIR, fname)
        try:
            if now - os.path.getmtime(fpath) > CACHE_TTL:
                os.remove(fpath)
        except OSError:
            pass


@st.cache_data(ttl=86400, show_spinner=False)
def _run_cleanup(_day: int) -> None:
    _cleanup_cache()


_run_cleanup(int(time.time() // 86400))

st.set_page_config(page_title="Norwegian DOCX Translator", page_icon="\U0001f310")
st.title("Norwegian \u2192 English DOCX Translator")
st.caption("Powered by Azure Batch Document Translation \u2014 formatting preserved.")

if "results" not in st.session_state:
    st.session_state.results = {}  # {original_filename: cache_key}

uploaded_files = st.file_uploader(
    "Upload Norwegian Word documents",
    type=["docx"],
    accept_multiple_files=True,
)

source_lang = st.selectbox(
    "Source language",
    options=["auto", "nb", "nn"],
    format_func=lambda x: {
        "auto": "Auto-detect",
        "nb": "Norwegian Bokm\u00e5l (nb)",
        "nn": "Norwegian Nynorsk (nn)",
    }[x],
)

if uploaded_files:
    if st.button("Translate", type="primary"):
        st.session_state.results = {}
        file_data = {f.name: f.read() for f in uploaded_files}

        progress_slot = st.empty()
        results_slot = st.empty()
        statuses: dict[str, str] = {name: "Queued..." for name in file_data}
        partial: dict[str, dict] = {}  # {filename: {key, has_docx, has_txt}}
        lock = threading.Lock()
        ctx = get_script_run_ctx()

        def refresh_progress() -> None:
            with lock:
                current = dict(statuses)
            if current:
                progress_slot.markdown(
                    "\n\n".join(f"\u23f3 `{n}` \u2014 {m}" for n, m in current.items())
                )
            else:
                progress_slot.empty()

        def refresh_results() -> None:
            with lock:
                current = {k: dict(v) for k, v in partial.items()}
            if not current:
                results_slot.empty()
                return
            rows = ""
            for fname, info in current.items():
                key = info["key"]
                base = fname.replace(".docx", "_en")
                if info["has_docx"]:
                    docx_cell = f'<a href="/app/static/{key}.docx" download="{base}.docx">{base}.docx</a>'
                else:
                    docx_cell = f'<span style="color:grey">{base}.docx &nbsp;\u23f3</span>'
                if info["has_txt"]:
                    txt_cell = f'<a href="/app/static/{key}.txt" download="{base}.txt">{base}.txt</a>'
                else:
                    txt_cell = f'<span style="color:grey">{base}.txt &nbsp;\u23f3</span>'
                rows += f"<tr><td>{docx_cell}</td><td>{txt_cell}</td></tr>"
            results_slot.markdown(
                "<style>"
                "table.trtable{border-collapse:collapse;width:100%}"
                "table.trtable th{text-align:left;border-bottom:1px solid #444;padding:4px 8px;font-size:0.85rem;color:grey}"
                "table.trtable td{padding:3px 8px;font-size:0.9rem}"
                "table.trtable a{text-decoration:none}"
                "table.trtable a:hover{text-decoration:underline}"
                "</style>"
                f'<table class="trtable"><thead><tr><th>DOCX</th><th>TXT</th></tr></thead>'
                f"<tbody>{rows}</tbody></table>",
                unsafe_allow_html=True,
            )

        refresh_progress()

        def process(filename: str):
            add_script_run_ctx(threading.current_thread(), ctx)
            key = uuid.uuid4().hex
            with lock:
                partial[filename] = {"key": key, "has_docx": False, "has_txt": False}
            refresh_results()

            def on_status(msg: str) -> None:
                with lock:
                    statuses[filename] = msg
                refresh_progress()

            def on_azure_done(docx_bytes: bytes) -> None:
                add_script_run_ctx(threading.current_thread(), ctx)
                _write_docx(key, docx_bytes)
                with lock:
                    partial[filename]["has_docx"] = True
                refresh_results()

            def on_claude_done(txt: str) -> None:
                add_script_run_ctx(threading.current_thread(), ctx)
                _write_txt(key, txt)
                with lock:
                    partial[filename]["has_txt"] = True
                refresh_results()

            try:
                translate_docx(
                    file_bytes=file_data[filename],
                    filename=filename,
                    source_lang=None if source_lang == "auto" else source_lang,
                    on_status=on_status,
                    on_azure_done=on_azure_done,
                    on_claude_done=on_claude_done,
                )
                return filename, key, None
            except Exception as exc:
                log.exception("Translation failed for '%s'", filename)
                return filename, None, exc

        with ThreadPoolExecutor(max_workers=len(file_data)) as pool:
            futures = {pool.submit(process, name): name for name in file_data}
            for future in as_completed(futures):
                filename, key, err = future.result()
                with lock:
                    statuses.pop(filename, None)
                if err:
                    log.error("Failed: %s", filename)
                    with lock:
                        partial.pop(filename, None)
                    refresh_results()
                else:
                    st.session_state.results[filename] = key
                refresh_progress()

        results_slot.empty()
        progress_slot.info("\u2705 All done!")

# Results — download links served directly from disk, zero RAM overhead
if st.session_state.results:
    rows = ""
    for filename, key in st.session_state.results.items():
        base = filename.replace(".docx", "_en")
        rows += (
            f"<tr>"
            f'<td><a href="/app/static/{key}.docx" download="{base}.docx">{base}.docx</a></td>'
            f'<td><a href="/app/static/{key}.txt" download="{base}.txt">{base}.txt</a></td>'
            f"</tr>"
        )
    n = len(st.session_state.results)
    zip_filename = _ensure_zip(st.session_state.results)
    zip_html = (
        f'<a class="zipbtn" href="/app/static/{zip_filename}" download="translations.zip">'
        f"\U0001f389 Download all as ZIP ({n * 2} files \u00b7 .docx + .txt)"
        f"</a>"
    )

    st.markdown(
        f"""
        <style>
            table.trtable {{border-collapse:collapse; width:100%}}
            table.trtable th {{text-align:left; border-bottom:1px solid #444; padding:4px 8px; font-size:0.85rem; color:grey}}
            table.trtable td {{padding:3px 8px; font-size:0.9rem}}
            table.trtable a {{text-decoration:none}}
            table.trtable a:hover {{text-decoration:underline}}
            a.zipbtn {{
                display:inline-block; margin-top:12px; padding:6px 16px;
                border:1px solid #555; border-radius:6px; font-size:0.9rem;
                text-decoration:none; color:inherit;
            }}
            a.zipbtn:hover {{border-color:#aaa}}
        </style>
        <table class="trtable">
            <thead><tr><th>DOCX</th><th>TXT</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
        {zip_html}
        """,
        unsafe_allow_html=True,
    )
