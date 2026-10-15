# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Local run loading, export packaging and Streamlit-independent job control."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import queue
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .pipeline import PipelineCancelled, run_pipeline

EXPORT_FILES = (
    "metadata.csv", "metadata.json", "articles.jsonl", "chunks.jsonl",
    "failures.jsonl", "duplicates.jsonl", "progress.jsonl", "manifest.json",
    "faiss_index.index", "chunk_metadata.json",
)
DATASET_FILES = EXPORT_FILES[:8]


def _require_dataset_files(run_dir, manifest):
    if manifest.get("status") in {"complete", "partial", "interrupted"}:
        missing = [name for name in DATASET_FILES if not (run_dir / name).is_file() or (run_dir / name).is_symlink()]
        if missing:
            raise ValueError("Saved dataset is incomplete; missing or unsafe artifacts: " + ", ".join(missing))


def studio_root():
    return config.path("dataset_studio")


def optional_dependencies(names):
    missing = []
    for name in names:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def load_local_embedder():
    """Opt-in availability check: never download a model or select CUDA."""
    missing = optional_dependencies(("numpy", "faiss", "sentence_transformers"))
    if missing:
        raise RuntimeError("Missing optional dependencies: " + ", ".join(missing))
    import numpy  # noqa: F401 — verify imports, not just package discovery
    import faiss  # noqa: F401
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.EMBED_MODEL, device="cpu", local_files_only=True)


def saved_runs(root=None):
    root = Path(root) if root is not None else studio_root()
    rows = []
    for path in sorted((root / "runs").glob("*/manifest.json"), reverse=True):
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf8"))
            rows.append({"path": str(path.parent.resolve()), "query": manifest.get("options", {}).get("query", "Untitled query"),
                         "status": manifest.get("status", "unknown"), "name": path.parent.name})
        except (OSError, ValueError, AttributeError):
            continue
    return rows


def load_run(run_dir):
    run_dir = Path(run_dir)
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf8"))
        records = {}
        for name in ("articles", "chunks", "failures", "duplicates", "progress"):
            path = run_dir / f"{name}.jsonl"
            records[name] = [json.loads(line) for line in path.read_text(encoding="utf8").splitlines() if line.strip()] if path.exists() else []
        if not isinstance(manifest, dict) or any(not isinstance(row, dict) for rows in records.values() for row in rows):
            raise ValueError("Invalid dataset record")
        _require_dataset_files(run_dir, manifest)
        for name in ("articles", "chunks", "failures", "duplicates"):
            if name in manifest and (type(manifest[name]) is not int or manifest[name] != len(records[name])):
                raise ValueError(f"Saved dataset is inconsistent: manifest {name} count does not match its records.")
        return {"run_dir": str(run_dir.resolve()), "manifest": manifest, **records}
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not open the saved dataset: {exc}") from exc


def export_files(dataset):
    """Allow only known run artifacts; never include cache responses or arbitrary files."""
    root = Path(dataset["run_dir"]).resolve()
    _require_dataset_files(root, dataset["manifest"])
    output = {}
    for name in EXPORT_FILES:
        if name in {"faiss_index.index", "chunk_metadata.json"} and not dataset["manifest"].get("index"):
            continue
        path = root / name
        if path.is_file() and not path.is_symlink() and path.resolve().parent == root:
            output[name] = path.read_bytes()
    if "manifest.json" not in output:
        raise ValueError("The run manifest is missing; a traceable export cannot be created.")
    return output


def zip_dataset(dataset):
    files = export_files(dataset)
    provenance = {
        "exported_at": datetime.now(timezone.utc).isoformat(), "source": "NCBI PubMed Central",
        "run_manifest": "manifest.json", "article_provenance": "articles.jsonl",
        "notice": "Source snapshots may be stale. Original article licenses apply to reuse and redistribution.",
        "files": [{"name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in files.items()],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        archive.writestr("export_manifest.json", json.dumps(provenance, ensure_ascii=False, indent=2))
    return buffer.getvalue()


def article_outcomes(events):
    rows = {}
    for event in events:
        pmcid, stage = event.get("pmcid"), event.get("stage")
        if not pmcid:
            continue
        if stage == "article_started":
            rows[pmcid] = {"PMCID": pmcid, "Status": "Processing", "Chunks": 0, "Details": ""}
        elif stage in {"article_completed", "article_failed", "article_duplicate"}:
            rows[pmcid] = {"PMCID": pmcid,
                           "Status": {"article_completed": "Collected", "article_failed": "Failed", "article_duplicate": "Duplicate"}[stage],
                           "Chunks": event.get("chunks", 0), "Details": event.get("error", event.get("duplicate_of", ""))}
    return list(rows.values())


class CollectionJob:
    """One local worker per browser session. Worker never calls Streamlit APIs."""
    def __init__(self, options, *, output_root=None, index=False, embedder=None, pipeline=None):
        self.options = options
        self.output_root = output_root
        self.index, self.embedder = index, embedder
        self.pipeline = pipeline or run_pipeline
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.result = None
        self.error = ""
        self.interrupted = False
        self.run_dir = None
        self.thread = threading.Thread(target=self._work, name="dataset-studio-collection", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _progress(self, event):
        if event.get("stage") == "run_started":
            self.run_dir = event["run_dir"]
        self.events.put(event)
        if self.cancel.is_set() and event.get("stage") not in {"complete", "interrupted", "failed"}:
            raise PipelineCancelled("Processing stopped. Completed articles have been saved.")

    def _work(self):
        try:
            self.result = self.pipeline(self.options, self.output_root, self._progress, index=self.index, embedder=self.embedder)
        except PipelineCancelled as exc:
            self.interrupted, self.error = True, str(exc)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.done.set()

    def drain(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events
