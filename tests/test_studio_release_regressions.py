# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Defects reproduced during the V1 release audit, using synthetic fixtures."""
import json
from pathlib import Path

import pytest

from biomedical_dataset_studio.pipeline import PipelineOptions, parse_xml, run_pipeline
from biomedical_dataset_studio.studio_support import export_files, load_run
from test_dataset_studio import FakeClient, xml


def test_jats_block_boundaries_do_not_fuse_words_or_split_inline_terms():
    payload = xml(body="Readable biomedical introduction.").replace(
        b"<p>Parent conclusion.</p>",
        b"<list><list-item><p>Clinical workflow</p></list-item><list-item><p>Patient outcomes</p></list-item></list>"
        b"<boxed-text><title>Care guidance</title><p>First paragraph.</p><p>Second paragraph.</p></boxed-text>"
        b"<p>Immuno<italic>therapy</italic> improves IL-<bold>6</bold> monitoring.</p>")
    article = parse_xml(payload, "PMC123")
    prose = " ".join(s["text"] for s in article["sections"])
    assert "Clinical workflow Patient outcomes" in prose
    assert "Care guidance First paragraph. Second paragraph." in prose
    assert "Immunotherapy improves IL-6 monitoring." in prose
    assert "workflowPatient" not in prose and "paragraph.Second" not in prose


def test_nested_list_in_abstract_keeps_block_boundaries():
    payload = xml().replace(b"<p>Abstract evidence</p>",
                            b"<p>Findings:<list><list-item><p>First result</p></list-item><list-item><p>Second result</p></list-item></list></p>")
    article = parse_xml(payload, "PMC123")
    abstract = article["sections"][0]["text"]
    assert "First result Second result" in abstract
    assert abstract.count("First result") == 1


def test_complete_manifest_cannot_open_without_dataset_files(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"status": "complete", "articles": 20, "chunks": 323}))
    with pytest.raises(ValueError, match="incomplete"):
        load_run(tmp_path)


@pytest.mark.parametrize("name", ["articles", "chunks", "failures", "duplicates"])
def test_truncated_jsonl_count_mismatch_is_reported(tmp_path, name):
    manifest = run_pipeline(PipelineOptions("test"), tmp_path, client=FakeClient())
    run = Path(manifest["run_dir"])
    (run / f"{name}.jsonl").write_text("")
    with pytest.raises(ValueError, match="count does not match"):
        load_run(run)


def test_missing_artifacts_cannot_be_exported_from_previously_loaded_session(tmp_path):
    manifest = run_pipeline(PipelineOptions("test"), tmp_path, client=FakeClient())
    dataset = load_run(manifest["run_dir"])
    (Path(manifest["run_dir"]) / "metadata.csv").unlink()
    with pytest.raises(ValueError, match="metadata.csv"):
        export_files(dataset)
