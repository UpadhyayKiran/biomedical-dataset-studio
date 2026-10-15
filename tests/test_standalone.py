# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Standalone packaging, workspace and licensing checks."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from biomedical_dataset_studio import config


def test_no_original_repository_import_is_needed():
    script = '''import importlib.abc,sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname == "biomedical_rag" or fullname.startswith("biomedical_rag."):
            raise AssertionError("Original repository dependency")
sys.meta_path.insert(0,Guard())
from biomedical_dataset_studio.pipeline import PipelineOptions
from biomedical_dataset_studio.studio_support import CollectionJob
assert PipelineOptions("biomedical evidence").article_limit == 20
assert not any(n.startswith("biomedical_rag") for n in sys.modules)
'''
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)


def test_workspace_uses_only_standalone_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("BIOMEDICAL_DATASET_STUDIO_WORKSPACE", str(tmp_path / "standalone"))
    monkeypatch.setenv("BIOMEDICAL_RAG_WORKSPACE", str(tmp_path / "unused"))
    assert config.path("dataset_studio") == tmp_path / "standalone" / "dataset_studio"


def test_official_apache_license_is_unmodified():
    root = Path(__file__).resolve().parents[1]
    provenance = json.loads((root / "docs" / "SOURCE_PROVENANCE.json").read_text())
    assert hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest() == provenance["apache_license_sha256"]
    assert "Copyright 2026 Kiran Upadhyay" in (root / "NOTICE").read_text()


def test_python_files_have_spdx_attribution():
    root = Path(__file__).resolve().parents[1]
    paths = [root / "dataset_studio_app.py", *list((root / "biomedical_dataset_studio").glob("*.py")), *list((root / "tests").glob("*.py"))]
    for path in paths:
        header = path.read_text(encoding="utf8").splitlines()[:3]
        assert "# SPDX-FileCopyrightText: 2026 Kiran Upadhyay" in header
        assert "# SPDX-License-Identifier: Apache-2.0" in header
