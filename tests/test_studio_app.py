# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Streamlit integration tests plus real backend/export and server smoke tests."""
import hashlib
import io
import json
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from biomedical_dataset_studio import studio_support as support
from biomedical_dataset_studio.pipeline import PipelineCancelled, PipelineError, PipelineOptions, run_pipeline
from test_dataset_studio import FakeClient, xml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dataset_studio_app.py"


@pytest.fixture
def app_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOMEDICAL_DATASET_STUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(support, "run_pipeline", lambda options, root, callback, **kwargs:
                        run_pipeline(options, root, callback, client=FakeClient(), **kwargs))
    return tmp_path


def app():
    return AppTest.from_file(str(APP), default_timeout=15).run()


def finish(at):
    job = at.session_state["studio_job"]
    if job:
        job.thread.join(timeout=10)
        assert job.done.is_set()
    at.run()
    assert not at.exception
    return at


def collect(at):
    at.text_input(key="studio_query").set_value("clinical evidence")
    at.number_input(key="studio_limit").set_value(4)
    at.button(key="FormSubmitter:studio_create-Create dataset").click().run()
    return finish(at)


def test_launch_and_validation_do_not_start_collection(app_environment):
    at = app()
    assert not at.exception
    assert [t.label for t in at.tabs][:3] == ["Create Dataset", "Explore Dataset", "Export Dataset"]
    assert at.title[0].value == "Biomedical Dataset Studio"
    at.button(key="FormSubmitter:studio_create-Create dataset").click().run()
    assert any("non-empty" in error.value for error in at.error)
    assert at.session_state["studio_job"] is None
    assert not (app_environment / "dataset_studio" / "runs").exists()


def test_collection_explore_export_and_rerun_persistence(app_environment):
    at = collect(app())
    dataset = at.session_state["studio_dataset"]
    assert dataset["manifest"]["articles"] == 1 and len(dataset["failures"]) == 1
    assert [m.value for m in at.metric] == ["1", "1", "1", "2"]
    assert len(at.get("download_button")) == 4
    assert any("incomplete" in w.value for w in at.warning)
    at.button(key="studio_prepare_zip").click().run()
    assert not at.exception and len(at.get("download_button")) == 5
    zip_bytes = at.session_state["studio_zip"]
    at.selectbox(key="studio_article_" + Path(dataset["run_dir"]).name).set_value(0).run()
    assert at.session_state["studio_dataset"]["run_dir"] == dataset["run_dir"]
    assert at.session_state["studio_zip"] == zip_bytes
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        assert "export_manifest.json" in archive.namelist()
        assert json.loads(archive.read("manifest.json"))["status"] == "partial"


def test_empty_search_and_downloads(app_environment, monkeypatch):
    class Empty:
        def discover(self):
            return []
    monkeypatch.setattr(support, "run_pipeline", lambda options, root, callback, **kwargs:
                        run_pipeline(options, root, callback, client=Empty(), **kwargs))
    at = collect(app())
    assert any("No articles matched" in info.value for info in at.info)
    assert len(at.get("download_button")) == 4
    assert at.session_state["studio_dataset"]["manifest"]["status"] == "complete"


def test_network_error_retains_previous_dataset(app_environment, monkeypatch):
    at = collect(app())
    previous = at.session_state["studio_dataset"]["run_dir"]
    def broken(*args, **kwargs):
        raise PipelineError("Network unavailable; check connectivity.")
    monkeypatch.setattr(support, "run_pipeline", broken)
    at.button(key="FormSubmitter:studio_create-Create dataset").click().run()
    finish(at)
    assert at.session_state["studio_dataset"]["run_dir"] == previous
    assert any("Network unavailable" in e.value for e in at.error)


def test_open_saved_run_after_new_session(app_environment):
    first = collect(app())
    run = first.session_state["studio_dataset"]["run_dir"]
    at = app()
    assert at.session_state["studio_dataset"] is None
    at.button(key="studio_open_saved").click().run()
    assert not at.exception
    assert at.session_state["studio_dataset"]["run_dir"] == run


def test_optional_index_is_disabled_without_dependencies(app_environment, monkeypatch):
    from biomedical_dataset_studio import studio_ui
    monkeypatch.setattr(studio_ui, "optional_dependencies", lambda names: list(names))
    at = app()
    assert at.checkbox(key="studio_index").disabled
    assert at.button(key="studio_check_model").disabled
    assert at.checkbox(key="studio_pdf").disabled
    collect(at)
    assert at.session_state["studio_dataset"]["manifest"].get("index") is None


def test_local_model_error_is_visible_and_index_stays_disabled(app_environment, monkeypatch):
    from biomedical_dataset_studio import studio_ui
    monkeypatch.setattr(studio_ui, "optional_dependencies", lambda names: [])
    def unavailable(*args):
        raise OSError("Model is not cached")
    monkeypatch.setattr(studio_ui, "checked_embedder", unavailable)
    at = app()
    at.button(key="studio_check_model").click().run()
    assert not at.exception
    assert at.checkbox(key="studio_index").disabled
    assert any("not cached" in w.value for w in at.warning)


def test_invalid_overlap_is_rejected(app_environment):
    at = app()
    at.text_input(key="studio_query").set_value("clinical")
    at.number_input(key="studio_overlap").set_value(500)
    at.button(key="FormSubmitter:studio_create-Create dataset").click().run()
    assert not at.exception
    assert any("chunk_size" in e.value for e in at.error)


def test_optional_index_available_path_and_zip_contains_aligned_index(app_environment, monkeypatch):
    pytest.importorskip("faiss")
    import numpy as np
    from biomedical_dataset_studio import studio_ui
    class Embedder:
        def encode(self, texts, **kwargs):
            return np.ones((len(texts), 2), dtype="float32")
    monkeypatch.setattr(studio_ui, "optional_dependencies", lambda names: [])
    monkeypatch.setattr(studio_ui, "checked_embedder", lambda name: Embedder())
    at = app()
    at.button(key="studio_check_model").click().run()
    assert not at.checkbox(key="studio_index").disabled
    at.checkbox(key="studio_index").check()
    collect(at)
    dataset = at.session_state["studio_dataset"]
    assert dataset["manifest"]["index"]["vectors"] == len(dataset["chunks"])
    with zipfile.ZipFile(io.BytesIO(support.zip_dataset(dataset))) as archive:
        assert "faiss_index.index" in archive.namelist()
        metadata = json.loads(archive.read("chunk_metadata.json"))
        assert metadata[0]["faiss_id"] == 0 and metadata[0]["licenses"]


def test_index_failure_keeps_article_exports(app_environment, monkeypatch):
    pytest.importorskip("faiss")
    import numpy as np
    from biomedical_dataset_studio import studio_ui
    class BrokenEmbedder:
        def encode(self, texts, **kwargs):
            return np.zeros((len(texts), 2), dtype="float32")
    monkeypatch.setattr(studio_ui, "optional_dependencies", lambda names: [])
    monkeypatch.setattr(studio_ui, "checked_embedder", lambda name: BrokenEmbedder())
    at = app()
    at.button(key="studio_check_model").click().run()
    at.checkbox(key="studio_index").check()
    collect(at)
    dataset = at.session_state["studio_dataset"]
    assert any("Index generation failed" in w.value for w in at.warning)
    assert dataset["articles"] and len(at.get("download_button")) == 4
    assert "faiss_index.index" not in support.export_files(dataset)


def test_document_with_no_eligible_chunks_remains_explorable(app_environment, monkeypatch):
    class Short:
        def discover(self):
            return ["PMC123"]
        def fetch_xml(self, pmcid):
            return xml(body="Short readable clinical body."), {"format": "jats_xml"}
    monkeypatch.setattr(support, "run_pipeline", lambda options, root, callback, **kwargs:
                        run_pipeline(options, root, callback, client=Short(), **kwargs))
    at = collect(app())
    assert any("No chunks met" in info.value for info in at.info)
    assert len(at.session_state["studio_dataset"]["articles"]) == 1
    assert at.session_state["studio_dataset"]["chunks"] == []


def test_cancellation_preserves_completed_articles_and_exports(tmp_path):
    def progress(event):
        if event["stage"] == "article_completed":
            raise PipelineCancelled("User stopped collection")
    with pytest.raises(PipelineCancelled):
        run_pipeline(PipelineOptions("x"), tmp_path, progress, client=FakeClient())
    run = next((tmp_path / "runs").iterdir())
    dataset = support.load_run(run)
    assert dataset["manifest"]["status"] == "interrupted"
    assert len(dataset["articles"]) == 1 and len(dataset["chunks"]) == 1
    assert dataset["progress"][-1]["stage"] == "interrupted"
    assert json.loads(support.export_files(dataset)["metadata.json"])[0]["pmcid"] == "PMC123"


def test_ui_stop_processing(app_environment, monkeypatch):
    import threading
    gate = threading.Event()
    def controlled(options, root, callback, **kwargs):
        def progress(event):
            callback(event)
            if event["stage"] == "article_completed":
                assert gate.wait(10)
        return run_pipeline(options, root, progress, client=FakeClient(), **kwargs)
    monkeypatch.setattr(support, "run_pipeline", controlled)
    at = app()
    at.text_input(key="studio_query").set_value("clinical")
    at.button(key="FormSubmitter:studio_create-Create dataset").click().run()
    job = at.session_state["studio_job"]
    assert job is not None
    at.button(key="studio_stop").click().run()
    assert job.cancel.is_set()
    gate.set()
    finish(at)
    assert at.session_state["studio_dataset"]["manifest"]["status"] == "interrupted"
    assert len(at.session_state["studio_dataset"]["articles"]) == 1
    assert any("interrupted" in w.value.lower() for w in at.warning)


def test_zip_integrity_exact_export_bytes_and_excludes_unrelated_files(tmp_path):
    manifest = run_pipeline(PipelineOptions("x"), tmp_path, client=FakeClient())
    dataset = support.load_run(manifest["run_dir"])
    root = Path(dataset["run_dir"])
    (root / "private.txt").write_text("must not be exported")
    files = support.export_files(dataset)
    bundle = support.zip_dataset(dataset)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert archive.testzip() is None
        assert "private.txt" not in archive.namelist()
        assert set(archive.namelist()) == set(files) | {"export_manifest.json"}
        inventory = json.loads(archive.read("export_manifest.json"))
        for entry in inventory["files"]:
            payload = archive.read(entry["name"])
            assert payload == files[entry["name"]]
            assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
            assert len(payload) == entry["bytes"]


def test_corrupt_saved_dataset_error(tmp_path):
    run = tmp_path / "runs" / "bad"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text("invalid")
    assert support.saved_runs(tmp_path) == []
    with pytest.raises(ValueError, match="Could not open"):
        support.load_run(run)


def test_local_embedder_uses_cpu_and_never_downloads(monkeypatch):
    pytest.importorskip("faiss")
    import types
    calls = []
    monkeypatch.setattr(support, "optional_dependencies", lambda names: [])
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(
        SentenceTransformer=lambda *args, **kwargs: calls.append((args, kwargs)) or object()))
    support.load_local_embedder()
    assert calls[0][1] == {"device": "cpu", "local_files_only": True}


def test_real_streamlit_server_health():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(APP),
        "--server.headless=true", "--server.address=127.0.0.1", f"--server.port={port}",
        "--browser.gatherUsageStats=false"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)
                if response.status_code == 200:
                    assert response.text == "ok"
                    assert requests.get(f"http://127.0.0.1:{port}", timeout=2).status_code == 200
                    break
            except requests.RequestException:
                pass
            if process.poll() is not None:
                pytest.fail(process.stdout.read().decode(errors="replace"))
            time.sleep(0.2)
        else:
            pytest.fail("Streamlit did not become healthy within 20 seconds")
    finally:
        process.terminate()
        process.communicate(timeout=10)
