<!-- SPDX-FileCopyrightText: 2026 Kiran Upadhyay -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Biomedical Dataset Studio v1.0.0

First independent source release of the validated local Biomedical Dataset Studio.

- PMC OA discovery, structured JATS collection, metadata/text cleanup, exact deduplication and source-attributed chunks.
- Streamlit Create, Explore and Export workflow with progress, caching/retry, saved runs and checkpoint cancellation.
- CSV, JSON/JSONL and ZIP exports retaining article licenses/provenance and SHA-256 checksums.
- Optional permitted PDF fallback and CPU FAISS generation; no BioMistral or GPU requirement for collection.
- Independent package/configuration, Apache-2.0 source license, SPDX attribution, NOTICE and dependency/source provenance.

Validation: **53 tests passed in both the existing and a fresh isolated Windows Python 3.12 environment**. Real Streamlit server launch passed. Live standalone collection produced **20 articles and 323 chunks with zero failures**; export checksums passed. The original repository and its historical artifacts remained unchanged.

Install from the source checkout with `python -m pip install -e .`, then run `python -m streamlit run dataset_studio_app.py`. CLI: `python -m biomedical_dataset_studio "your biomedical query" --limit 20`.

The Apache-2.0 grant covers the Studio source. Downloaded articles and model weights retain their own licenses. Optional PyMuPDF is AGPL/commercial and the default optional embedding model is CC BY-NC 2.0; neither is relicensed or bundled here. Read THIRD_PARTY_NOTICES.md before using or redistributing optional combinations.

Scope: local, single-user V1. Cancellation is cooperative, exports use memory, and rate limits are not coordinated across processes. Live PDF retrieval, real-model embeddings, cross-platform installation and multi-user load tests were not executed. See docs/VALIDATION.md for exact evidence and remaining limits. No patent ownership claim is made.
