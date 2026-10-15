<!-- SPDX-FileCopyrightText: 2026 Kiran Upadhyay -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Standalone V1 validation — 15 October 2026

## Executed checks

- **53 tests passed** in the pre-existing validation environment (Streamlit 1.49.1), and **53 passed** in a newly created isolated Windows Python 3.12 virtual environment (Streamlit 1.66.0). No skips or warnings were reported in those runs. The isolated environment has no system-site-packages, original capstone package, Torch, Transformers or Sentence Transformers.
- The suite includes the **49 applicable Studio tests** extracted from the 55-test source repository, plus four standalone packaging/configuration/license cases. The six RAG-only workflow/index batch tests remain in the original repository and are not part of this product. Their omission is not a test pass claim.
- Tests cover native JATS metadata/sections and block boundaries, nested abstract deduplication, identifiers, malformed/restricted/abstract-only inputs, options, chunk offsets/exact deduplication, retries, cache integrity/secret redaction, limits, exports, partial failures, cancellation, corrupt saved-run rejection, optional PDF parsing and normalized/aligned FAISS output.
- Streamlit AppTest exercised launch, form validation, collection, exploration, individual/ZIP downloads, reruns, saved-run reopening, empty and partial results, network errors, local-model errors, successful/failed synthetic-vector indexing and the Stop action. A real subprocess launched `python -m streamlit run dataset_studio_app.py`, returned HTTP 200 `ok` at `/_stcore/health`, served the page and was stopped after the smoke test.
- Fresh dependency installation used `python -m pip install -e ".[test,pdf]" faiss-cpu`. `python -m pip check` returned **No broken requirements found**. PyMuPDF and native FAISS were installed to execute their tests; the embedding stack and model weights were not installed in that fresh environment.
- Built the standalone Python wheel with `python -m pip wheel . --no-deps --wheel-dir dist`, verified its unmodified Apache license and NOTICE, installed the wheel (replacing the editable package), and imported it from an unrelated temporary working directory. The original `biomedical_rag` package and Torch were unavailable there. Console CLI packaging and standalone workspace resolution were exercised.
- AST comparisons confirmed **16 extracted helper functions** exactly match their original bodies. The complete Studio pipeline/UI/support algorithms were retained with standalone imports, package configuration and SPDX attribution. Unused batch collectors, training/generation code and import-time folder creation were excluded.

## Live standalone collection

A fresh-environment Streamlit AppTest run used `remote patient monitoring AND cc_by_license[filter]`, article limit 20, with indexing and PDF fallback disabled.

Observed: **20 articles, 323 chunks, zero failures, 21 HTTP 200 requests**, minimum sequential request-start interval **0.469 seconds**. Only official E-Utilities and PMC OAI-PMH hosts were contacted. Article licenses and source hashes were present; CSV article counts and chunk JSONL counts matched the in-memory datasets. ZIP CRC, exact members and all SHA-256 inventory entries passed. No original-capstone, ML/GPU or PDF module was imported during standard collection. Generated article/cache/export artifacts were kept in ignored `workspace/`, not committed or released.

The prior source-project audit had additionally compared all 20 article identifiers/metadata/source XML and all 323 exact chunk slices, verified three-article checkpoint cancellation, injected retry backoff and partial-failure recovery, and restarted/reopened the app. Those are historical source-project checks; the standalone release relies on its executed 53-test suite and live collection described above rather than claiming those manual fault injections were rerun here.

## Publication and preservation

The original source repository was not edited. All **161 snapshotted non-Git/non-cache files**, including existing generated datasets and historical outputs, retained their SHA-256 values; its Git status also remained unchanged. No original history, results, model weights or literature datasets were copied into the standalone Git history.

The publication candidate is scanned for credential patterns, personal contact details, local paths and large/generated artifacts before committing. Required software copyright attribution and the GitHub maintainer identity are intentional. `LICENSE` is byte-identical to the official Apache Software Foundation download, with attribution supplied separately by SPDX headers and NOTICE.

`DEPENDENCIES.json` records resolved metadata for 35 default packages, optional PDF/native-index packages and test dependencies in the fresh environment. A separate metadata-only group records 32 optional embedding-stack packages from the existing validation environment. This is not a universal lockfile or clearance for future versions. Optional PyMuPDF's AGPL/commercial terms and model-weight noncommercial terms remain explicit in the licensing audit.

## Limits and unexecuted checks

Local single-user use is the validated scope. There is no cross-process rate-limit coordinator, automatic continuation after interruption or durable checkpoint on hard process termination. Large exports use memory. Near-duplicate detection, full mathematical/table preservation and clinical validation are not implemented.

Live PDF fallback, real-model embedding generation, Linux/macOS installation, browser visual/accessibility testing, multi-user operation and large-scale stress/performance testing were not executed for this standalone release. The optional paths were tested using synthetic PDFs/vectors and missing-model cases. No screenshots are bundled; no visual QA claim is made.

The application release version is **1.0.0**. Processing provenance retains **1.0.1**, the audited XML-correction version inherited from the source pipeline.
