<!-- SPDX-FileCopyrightText: 2026 Kiran Upadhyay -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Usage and processing contract

Launch from the repository root with `python -m streamlit run dataset_studio_app.py`. The three sections are Create Dataset, Explore Dataset and Export Dataset. Results and prepared downloads survive widget reruns; disk-backed saved runs survive app restarts.

The CLI is `python -m biomedical_dataset_studio QUERY --limit 20`. Flags include `--output PATH`, `--chunk-size 500`, `--overlap 100`, `--refresh`, `--pdf-fallback`, and `--index`. Limits are 1–10,000 candidates because ESearch results are capped. CLI exit codes: 0 complete, 1 partial, 2 configuration/acquisition failure.

## Sources and processing

Discovery uses E-Utilities with OA and embargo filters. Full text uses the updated PMC OAI-PMH JATS endpoint. No retired OA Web Service, deprecated FTP path or article-page scraping is used. The opt-in fallback enumerates current Cloud versions with pagination and reads their metadata URLs, trying XML before PDF. Version ordering is deterministic, not a claim that the highest version is newest.

PDF fallback accepts only the backend's explicit CC0/CC BY/CC BY-SA license codes and publisher-permitted PDF URLs. Unknown, TDM, noncommercial and no-derivatives PDF licenses are excluded. XML follows PMC full-text dissemination permissions and preserves original license statements. Access is not unrestricted redistribution permission.

JATS parsing validates the returned PMCID, preserves metadata, section boundaries and paragraph text, excludes non-prose artifacts, separates block boundaries and avoids duplicated nested abstract paragraphs. Text cleanup uses NFKC and whitespace normalization. Chunking uses configurable word windows, minimum-information/numeric filters and exact per-article duplicate fingerprints. Shared wording in distinct articles retains its attribution. Exact full-document duplicates are recorded separately.

## Resilience and saved runs

Requests have timeouts, a minimum interval of 0.34 seconds and bounded retries. HTTP 408/429/5xx and transport failures receive exponential backoff with Retry-After support; other HTTP errors fail immediately. Source responses are cached for 24 hours unless refreshed. The client makes sequential requests within each job, but does not coordinate other processes.

Per-article failures continue the run and create `failures.jsonl`. A discovery failure writes a failed manifest and leaves the UI's previous dataset available. A cooperative stop saves completed articles and marks the run interrupted. Complete/partial/interrupted runs with missing required artifacts or manifest count mismatches are rejected on reopening. Export rejects required files removed after the session loaded them.

The application does not automatically resume an interrupted run; starting again can reuse cached source responses. Closing a browser does not cancel its worker. Hard process termination is not a durable checkpoint.

## Provenance and exports

Article and chunk provenance includes source endpoint/public parameters, source SHA-256, retrieval and processing timestamps, cache state, pipeline version and processing settings. ETag/Last-Modified and Cloud version metadata are retained where supplied. Contact address/API key request parameters are excluded from cache contents and provenance.

CSV lists/objects are JSON encoded. `articles.jsonl` contains metadata and structured sections; `chunks.jsonl` contains source-attributed windows with section IDs and word offsets. Audit files record failures, duplicates and progress. The run manifest records status/options/counts. A ZIP includes these artifacts and `export_manifest.json`, an inventory of exact byte counts and SHA-256 values. Raw cached responses and unrelated files are excluded.

Individual datasets can contain licensed article text. Review article terms before sharing either individual files or the complete ZIP.

## Optional indexing

Install the `index` extra only if needed. The UI's **Check local embedding model** imports the optional packages and loads the configured model with `device="cpu"` and `local_files_only=True`; missing dependencies or an unavailable model keep indexing disabled. The model can be configured with `BIOMEDICAL_DATASET_STUDIO_EMBED_MODEL`. No model is bundled. The default model's CC BY-NC 2.0 terms do not become Apache-2.0.

Normalized float32 vectors use FAISS inner-product indexing, with aligned metadata retaining licenses and provenance. Invalid vectors or failed indexing leave article exports available. CLI `--index` can fetch its configured model; the UI cannot.
