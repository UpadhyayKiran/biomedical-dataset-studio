# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Streamlit presentation for the existing Biomedical Dataset Studio pipeline."""
from pathlib import Path

import streamlit as st

from . import config
from .pipeline import PipelineOptions
from .studio_support import (
    CollectionJob, article_outcomes, export_files, load_local_embedder, load_run,
    optional_dependencies, saved_runs, zip_dataset,
)


@st.cache_resource(show_spinner=False)
def checked_embedder(model_name):
    # The argument makes cache invalidation explicit when configured model changes.
    return load_local_embedder()


def select_dataset(dataset):
    st.session_state.studio_dataset = dataset
    st.session_state.studio_zip = None
    st.session_state.studio_exports = None


def finish_job(job):
    """Consume a finished worker without losing the previous dataset on a failed search."""
    st.session_state.studio_events.extend(job.drain())
    st.session_state.studio_notice = job.error
    st.session_state.studio_notice_kind = "warning" if job.interrupted else "error"
    run_dir = job.result.get("run_dir") if job.result else job.run_dir
    if run_dir:
        try:
            dataset = load_run(run_dir)
            if job.result is not None or job.interrupted:
                select_dataset(dataset)
        except ValueError as exc:
            st.session_state.studio_notice = str(exc)
    st.session_state.studio_job = None


def render_progress():
    job = st.session_state.studio_job
    if job:
        st.session_state.studio_events.extend(job.drain())
        if job.done.is_set():
            finish_job(job)
            st.rerun()
    events = st.session_state.studio_events
    if not events and not job:
        return
    outcomes = article_outcomes(events)
    total = max((e.get("total", 0) for e in events), default=0)
    completed = sum(row["Status"] != "Processing" for row in outcomes)
    if job:
        latest = events[-1] if events else {}
        messages = {"discovery": "Searching PMC…", "cache_hit": "Reusing a cached source…",
                    "retry": f"Retrying a request in {latest.get('delay', 0):g} seconds…",
                    "index_started": "Building the CPU FAISS index…", "pdf_fallback": "Checking permitted fallback sources…"}
        label = messages.get(latest.get("stage"), f"Processing articles: {completed} of {total}" if total else "Starting collection…")
        st.progress(min(completed / total, 1.0) if total else 0.0, text=label)
        if st.button("Stop processing", disabled=job.cancel.is_set(), key="studio_stop"):
            job.cancel.set()
            st.rerun()
        if job.cancel.is_set():
            st.info("Stopping at the next processing checkpoint. An in-flight request may finish first.")
    if outcomes:
        st.dataframe(outcomes, hide_index=True, width="stretch")
    with st.expander("Processing log"):
        st.dataframe([{k: e.get(k, "") for k in ("timestamp", "stage", "pmcid", "error")} for e in events[-200:]],
                     hide_index=True, width="stretch")


def create_dataset():
    st.subheader("Create Dataset")
    st.caption("Collect open-access biomedical literature from PMC and turn it into traceable, structured datasets.")
    running = st.session_state.studio_job is not None
    missing_index = optional_dependencies(("numpy", "faiss", "sentence_transformers"))
    with st.expander("Optional FAISS index"):
        st.caption(f"Embedding model: {config.EMBED_MODEL}. Collection works without an index.")
        if missing_index:
            st.info("Indexing unavailable. Missing optional packages: " + ", ".join(missing_index))
        if st.button("Check local embedding model", disabled=running or bool(missing_index), key="studio_check_model"):
            try:
                with st.spinner("Checking the local model on CPU…"):
                    st.session_state.studio_embedder = checked_embedder(config.EMBED_MODEL)
                    st.session_state.studio_model_name = config.EMBED_MODEL
                st.session_state.studio_model_error = ""
            except Exception as exc:
                st.session_state.studio_embedder = None
                st.session_state.studio_model_error = f"Local model unavailable: {exc}"
        if st.session_state.studio_model_error:
            st.warning(st.session_state.studio_model_error)
        model_ready = st.session_state.studio_embedder is not None and st.session_state.studio_model_name == config.EMBED_MODEL
        if model_ready:
            st.success("Local embedding model ready. Index generation will use CPU.")
    missing_pdf = optional_dependencies(("pymupdf",))
    with st.form("studio_create"):
        query = st.text_input("Biomedical search query", placeholder="e.g. atrial fibrillation mobile health", key="studio_query")
        limit = st.number_input("Article limit", min_value=1, max_value=10000, value=20, step=1, key="studio_limit",
                                help="Maximum discovered candidates. Failed or duplicate articles may reduce the final count.")
        with st.expander("Collection settings"):
            left, right = st.columns(2)
            size = left.number_input("Words per chunk", min_value=60, max_value=2000, value=500, step=10, key="studio_size")
            overlap = right.number_input("Chunk overlap (words)", min_value=0, max_value=1999, value=100, step=10, key="studio_overlap")
            pdf = st.checkbox("Allow permitted PDF fallback", disabled=bool(missing_pdf), key="studio_pdf",
                              help="Prefers XML. PDF fallback follows the backend's conservative license policy.")
            if missing_pdf:
                st.caption("PDF fallback needs PyMuPDF (AGPL/commercial terms; see third-party notices).")
            refresh = st.checkbox("Refresh sources instead of using cached responses", key="studio_refresh")
            generate_index = st.checkbox("Generate FAISS index", disabled=not model_ready, key="studio_index")
        submitted = st.form_submit_button("Create dataset", type="primary", disabled=running)
    if submitted:
        try:
            options = PipelineOptions(query=query, article_limit=int(limit), chunk_size=int(size), chunk_overlap=int(overlap),
                                      pdf_fallback=pdf and not missing_pdf, cache_ttl=0 if refresh else 86400)
            if generate_index and not model_ready:
                raise ValueError("Check the local embedding model before enabling indexing.")
            st.session_state.studio_notice = ""
            st.session_state.studio_events = []
            st.session_state.studio_job = CollectionJob(options, index=generate_index,
                embedder=st.session_state.studio_embedder if generate_index else None).start()
            st.rerun()
        except (ValueError, OSError, RuntimeError) as exc:
            st.error(str(exc))
    st.fragment(run_every=0.5 if st.session_state.studio_job else None)(render_progress)()


def explore_dataset():
    st.subheader("Explore Dataset")
    dataset = st.session_state.studio_dataset
    if dataset is None:
        st.info("Create a dataset or open a saved run to explore articles and chunks.")
        return
    manifest = dataset["manifest"]
    st.caption(manifest.get("options", {}).get("query", ""))
    columns = st.columns(4)
    for column, label, value in zip(columns, ("Articles", "Chunks", "Failures", "Duplicates"),
                                     (len(dataset[k]) for k in ("articles", "chunks", "failures", "duplicates"))):
        column.metric(label, value)
    if manifest.get("status") == "interrupted":
        st.warning("This run was interrupted. Only completed articles are included.")
    elif manifest.get("status") == "partial":
        st.warning("Collection is incomplete. Review article failures and index status below.")
    elif manifest.get("status") == "failed":
        st.error(manifest.get("error", "The saved run failed."))
    if manifest.get("index_error"):
        st.warning("Index generation failed: " + manifest["index_error"])
    if not dataset["articles"]:
        if manifest.get("discovered", 0) == 0 and manifest.get("status") == "complete":
            st.info("No articles matched this search. Try a broader query; the empty dataset can still be exported.")
        else:
            st.info("No complete articles were collected. Review the failures before trying again.")
    else:
        articles = dataset["articles"]
        rows = [{"PMCID": a["pmcid"], "Title": a.get("title", ""), "Journal": a.get("journal", ""), "Year": a.get("year", ""),
                 "Source": a.get("source_url", ""), "Format": a.get("provenance", {}).get("format", ""),
                 "License": "; ".join(l.get("url") or l.get("type") or "Recorded statement" for l in a.get("licenses", [])) or "Not recorded"} for a in articles]
        st.dataframe(rows, hide_index=True, width="stretch",
                     column_config={"Source": st.column_config.LinkColumn("Source")})
        selected = st.selectbox("Article", range(len(articles)), format_func=lambda i: f"{articles[i]['pmcid']} · {articles[i].get('title', '')}",
                                key="studio_article_" + Path(dataset["run_dir"]).name)
        article = articles[selected]
        document, chunk_tab, provenance = st.tabs(["Processed document", "Article chunks", "Sources & licenses"])
        with document:
            for section in article.get("sections", []):
                with st.expander(section.get("heading") or section.get("section", "Section")):
                    st.text(section.get("text", ""))
        with chunk_tab:
            chunks = [c for c in dataset["chunks"] if c.get("pmcid") == article["pmcid"]]
            if not chunks:
                st.info("No chunks met the content filters for this article. Its processed document remains available.")
            else:
                choice = st.selectbox("Chunk", range(len(chunks)), format_func=lambda i: f"{chunks[i]['section']} · {chunks[i]['chunk_id']}",
                                      key="studio_chunk_" + Path(dataset["run_dir"]).name + article["pmcid"])
                chunk = chunks[choice]
                st.caption(f"{len(chunk['chunk_text'].split())} words · offsets {chunk.get('word_start', 0)}–{chunk.get('word_end', 0)}")
                st.text(chunk["chunk_text"])
                with st.expander("Chunk metadata"):
                    st.json({k: v for k, v in chunk.items() if k != "chunk_text"})
        with provenance:
            st.text(article.get("source_url", ""))
            st.caption("Original terms apply to reuse and redistribution.")
            st.json(article.get("licenses", []))
            st.json(article.get("provenance", {}))
            with st.expander("Complete article metadata"):
                st.json({k: v for k, v in article.items() if k != "sections"})
    if dataset["failures"]:
        with st.expander("Article failures", expanded=True):
            st.dataframe(dataset["failures"], hide_index=True, width="stretch")
    if dataset["duplicates"]:
        with st.expander("Duplicate records"):
            st.dataframe([{k: v for k, v in row.items() if k not in {"provenance", "licenses"}} for row in dataset["duplicates"]],
                         hide_index=True, width="stretch")
    with st.expander("Processing statistics & manifest"):
        st.write({"Sections": sum(len(a.get("sections", [])) for a in dataset["articles"]),
                  "Chunk words": sum(len(c.get("chunk_text", "").split()) for c in dataset["chunks"]),
                  "Cached articles": sum(bool(a.get("provenance", {}).get("cache_hit")) for a in dataset["articles"])})
        st.json(manifest)


def export_dataset():
    st.subheader("Export Dataset")
    dataset = st.session_state.studio_dataset
    if dataset is None:
        st.info("Create a dataset or open a saved run to enable downloads.")
        return
    st.caption("Exports preserve identifiers, original licenses and source provenance. The ZIP includes a SHA-256 file inventory.")
    try:
        if st.session_state.studio_exports is None:
            st.session_state.studio_exports = export_files(dataset)
        files = st.session_state.studio_exports
        for label, name, mime in (("Metadata CSV", "metadata.csv", "text/csv"), ("Structured articles JSONL", "articles.jsonl", "application/x-ndjson"),
                                  ("Chunks JSONL", "chunks.jsonl", "application/x-ndjson"), ("Provenance manifest", "manifest.json", "application/json")):
            if name in files:
                st.download_button(label, files[name], file_name=name, mime=mime, key="download_" + name, on_click="ignore")
        if st.button("Prepare complete ZIP", key="studio_prepare_zip"):
            st.session_state.studio_zip = zip_dataset(dataset)
        if st.session_state.studio_zip is not None:
            st.download_button("Download complete ZIP", st.session_state.studio_zip,
                               file_name=Path(dataset["run_dir"]).name + ".zip", mime="application/zip", on_click="ignore")
        st.caption("Saved locally: " + dataset["run_dir"])
    except (ValueError, OSError) as exc:
        st.error(f"Export unavailable: {exc}")


def main():
    st.set_page_config(page_title="Biomedical Dataset Studio", layout="wide")
    defaults = {"studio_dataset": None, "studio_job": None, "studio_events": [], "studio_notice": "",
                "studio_notice_kind": "error", "studio_embedder": None, "studio_model_name": "", "studio_model_error": "",
                "studio_zip": None, "studio_exports": None}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    job = st.session_state.studio_job
    if job and job.done.is_set():
        finish_job(job)
    st.title("Biomedical Dataset Studio")
    st.caption("Search literature. Inspect evidence. Export reproducible datasets.")
    with st.sidebar:
        st.subheader("Saved datasets")
        runs = saved_runs()
        if runs:
            selected = st.selectbox("Saved run", range(len(runs)), format_func=lambda i: f"{runs[i]['query']} · {runs[i]['status']} · {runs[i]['name']}")
            if st.button("Open saved dataset", disabled=st.session_state.studio_job is not None, key="studio_open_saved"):
                try:
                    select_dataset(load_run(runs[selected]["path"]))
                    st.session_state.studio_notice = ""
                    st.session_state.studio_events = st.session_state.studio_dataset["progress"]
                except ValueError as exc:
                    st.session_state.studio_notice = str(exc)
        else:
            st.caption("Completed and interrupted runs will appear here.")
        st.divider()
        st.caption("Source: NCBI PubMed Central. Standard collection uses CPU and requires no language model.")
    if st.session_state.studio_notice:
        getattr(st, st.session_state.studio_notice_kind)(st.session_state.studio_notice)
    create, explore, export = st.tabs(["Create Dataset", "Explore Dataset", "Export Dataset"])
    with create:
        create_dataset()
    with explore:
        explore_dataset()
    with export:
        export_dataset()
