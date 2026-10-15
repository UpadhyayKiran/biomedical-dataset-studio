# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

import json
import sys
from pathlib import Path

import pytest
import requests

from biomedical_dataset_studio.pipeline import (
    CLOUD_URL, OAI_URL, PMCClient, PipelineError, PipelineOptions,
    build_index, chunk_article, clean_text, parse_xml, run_pipeline,
)


def xml(pmcid="PMC123", body=None):
    body = body or " ".join(f"evidence{chr(97 + i % 26)}" for i in range(160))
    return f'''<article xmlns="urn:jats" xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article">
    <front><journal-meta><journal-title>Test Journal</journal-title></journal-meta><article-meta>
    <article-id pub-id-type="pmcid">{pmcid}</article-id><article-id pub-id-type="pmid">42</article-id>
    <article-id pub-id-type="doi">10.1/test</article-id><title-group><article-title>Clinical <italic>evidence</italic> study</article-title></title-group>
    <pub-date><year>2026</year></pub-date><contrib-group><contrib contrib-type="author"><name><given-names>Ada</given-names><surname>Test</surname></name></contrib></contrib-group>
    <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/">CC BY</license></permissions>
    <abstract><p>Abstract evidence</p></abstract></article-meta></front>
    <body><sec id="s1"><title>Results</title><p>{body}</p>
    <sec id="s2"><title>Nested results</title><p>Nested prose α IL-6 1.5 mg.</p></sec>
    <p>Parent conclusion.</p><table-wrap><p>Table noise</p></table-wrap></sec></body>
    <back><ref-list><p>References noise</p></ref-list></back></article>'''.encode()


def test_structured_xml_metadata_and_nonduplicated_sections():
    article = parse_xml(xml(), "PMC123")
    assert article["title"] == "Clinical evidence study"
    assert article["pmid"] == "42" and article["doi"] == "10.1/test"
    assert article["authors"] == ["Ada Test"]
    assert article["licenses"][0]["url"].endswith("by/4.0/")
    assert article["year"] == "2026"
    joined = " ".join(s["text"] for s in article["sections"])
    assert joined.count("Nested prose") == 1
    assert "Table noise" not in joined and "References noise" not in joined
    assert len({s["section_id"] for s in article["sections"]}) == len(article["sections"])
    assert clean_text("α\u200b IL-6\n 1.5 mg") == "α IL-6 1.5 mg"


@pytest.mark.parametrize("payload,match", [
    (b"broken", "Invalid full-text XML"),
    (b'<OAI-PMH><error code="cannotDisseminateFormat">Rights restricted</error></OAI-PMH>', "Rights restricted"),
    (xml("PMC999"), "identifier mismatch"),
    (b"<article><front><article-meta><article-id pub-id-type='pmcid'>123</article-id><title-group><article-title>T</article-title></title-group><abstract><p>A</p></abstract></article-meta></front></article>", "abstract-only"),
])
def test_invalid_or_unavailable_xml(payload, match):
    with pytest.raises(PipelineError, match=match):
        parse_xml(payload, "PMC123")


@pytest.mark.parametrize("kwargs", [dict(query=" "), dict(query="x", article_limit=0),
    dict(query="x", article_limit=10001), dict(query="x", chunk_overlap=500),
    dict(query="x", retries=-1), dict(query="x", timeout=0), dict(query="x", cache_ttl=-1)])
def test_config_validation(kwargs):
    with pytest.raises(ValueError):
        PipelineOptions(**kwargs)


def test_chunk_windows_offsets_deduplication_and_rights():
    article = parse_xml(xml(body=" ".join("word" + chr(97 + i % 26) for i in range(650))), "PMC123")
    article["provenance"] = {"sha256": "test"}
    article["sections"].append(dict(article["sections"][1], section_id="duplicate"))
    chunks = chunk_article(article, PipelineOptions("clinical"))
    assert [len(c["chunk_text"].split()) for c in chunks] == [500, 250]
    assert [(c["word_start"], c["word_end"]) for c in chunks] == [(0, 500), (400, 650)]
    assert chunks[0]["licenses"] == article["licenses"]
    assert chunks[0]["provenance"] == article["provenance"]


class Response:
    def __init__(self, content=b"ok", status=200, headers=None):
        self.content, self.status_code, self.headers = content, status, headers or {}
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("test", response=self)


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_retry_cache_provenance_and_secret_redaction(tmp_path):
    session = Session([Response(status=429, headers={"Retry-After": "2"}), Response(xml())])
    events, delays = [], []
    client = PMCClient(tmp_path, PipelineOptions("x"), lambda **e: events.append(e), session, delays.append)
    payload, provenance = client.get(OAI_URL, {"email": "private", "api_key": "secret"})
    again, cached = client.get(OAI_URL, {"email": "private", "api_key": "secret"})
    assert payload == again and cached["cache_hit"]
    assert len(session.calls) == 2 and 2 in delays
    assert events[0]["stage"] == "retry"
    assert "api_key" not in provenance["request_params"]
    assert "secret" not in next(tmp_path.glob("*.json")).read_text()


def test_nonretryable_http_and_exhaustion(tmp_path):
    session = Session([Response(status=404)])
    client = PMCClient(tmp_path, PipelineOptions("x"), session=session, sleep=lambda _: None)
    with pytest.raises(PipelineError, match="HTTP 404"):
        client.get(OAI_URL)
    assert len(session.calls) == 1
    session = Session([requests.Timeout()] * 2)
    client = PMCClient(tmp_path, PipelineOptions("x", retries=1), session=session, sleep=lambda _: None)
    with pytest.raises(PipelineError, match="2 attempts"):
        client.get(OAI_URL)


def test_corrupt_cache_and_unsafe_url(tmp_path):
    session = Session([Response(b"first"), Response(b"second")])
    client = PMCClient(tmp_path, PipelineOptions("x"), session=session, sleep=lambda _: None)
    client.get(OAI_URL)
    next(tmp_path.glob("*.json")).write_text("broken")
    assert client.get(OAI_URL)[0] == b"second"
    with pytest.raises(PipelineError, match="official"):
        client.get("https://publisher.example/paper.pdf")


def test_discovery_filters_and_limit(tmp_path):
    payload = json.dumps({"esearchresult": {"idlist": ["1", "2"], "count": "50"}}).encode()
    session = Session([Response(payload)])
    client = PMCClient(tmp_path, PipelineOptions("immunotherapy", article_limit=2), session=session, sleep=lambda _: None)
    assert client.discover() == ["PMC1", "PMC2"]
    params = session.calls[0][1]["params"]
    assert "open_access[filter]" in params["term"] and params["retmax"] == 2


class FakeClient:
    def discover(self):
        return ["PMC123", "PMC999", "PMC124", "PMC123"]
    def fetch_xml(self, pmcid):
        if pmcid == "PMC999":
            raise PipelineError("Full text restricted")
        return xml(pmcid), {"source_url": OAI_URL, "sha256": "test", "retrieved_at": "test", "cache_hit": False}


def test_pipeline_exports_partial_failures_and_isolated_reruns(tmp_path):
    events = []
    options = PipelineOptions("clinical", article_limit=4)
    manifest = run_pipeline(options, tmp_path, events.append, client=FakeClient())
    run = Path(manifest["run_dir"])
    assert manifest["status"] == "partial"
    assert (manifest["articles"], manifest["failures"], manifest["duplicates"]) == (1, 1, 2)
    assert json.loads((run / "failures.jsonl").read_text())["pmcid"] == "PMC999"
    metadata = json.loads((run / "metadata.json").read_text())
    assert "sections" not in metadata[0] and "licenses" in metadata[0]
    assert "sections" in json.loads((run / "articles.jsonl").read_text())
    assert (run / "metadata.csv").read_text().startswith("pmcid,")
    assert any(e["stage"] == "article_failed" for e in events)
    assert events[-1]["stage"] == "complete"
    second = run_pipeline(options, tmp_path, client=FakeClient())
    assert second["run_dir"] != manifest["run_dir"]
    assert json.loads((run / "manifest.json").read_text()) == manifest


def test_discovery_failure_manifest_and_empty_export(tmp_path):
    class Broken:
        def discover(self):
            raise PipelineError("Search unavailable")
    with pytest.raises(PipelineError, match="Search unavailable"):
        run_pipeline(PipelineOptions("x"), tmp_path, client=Broken())
    manifest = json.loads(next(tmp_path.glob("runs/*/manifest.json")).read_text())
    assert manifest["status"] == "failed"
    class Empty:
        def discover(self):
            return []
    manifest = run_pipeline(PipelineOptions("x"), tmp_path, client=Empty())
    assert manifest["articles"] == 0 and manifest["status"] == "complete"
    assert (Path(manifest["run_dir"]) / "chunks.jsonl").read_text() == ""


def test_pdf_fallback_license_policy_and_pagination(tmp_path):
    pages = [b'<ListBucketResult><IsTruncated>true</IsTruncated><NextContinuationToken>next</NextContinuationToken></ListBucketResult>',
             b'<ListBucketResult><CommonPrefixes><Prefix>PMC123.7/</Prefix></CommonPrefixes><IsTruncated>false</IsTruncated></ListBucketResult>']
    session = Session([Response(p) for p in pages] + [Response(json.dumps({"pmcid": "PMC123", "license_code": "CC BY-NC-ND"}).encode())])
    client = PMCClient(tmp_path, PipelineOptions("x"), session=session, sleep=lambda _: None)
    with pytest.raises(PipelineError, match="license policy"):
        client.pdf_article("PMC123")
    assert len(session.calls) == 3
    assert session.calls[1][1]["params"]["continuation-token"] == "next"


def test_pdf_fallback_uses_cloud_metadata_and_existing_parser(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox((30, 30, 550, 800), "Results\n" + "clinical evidence outcomes " * 45)
    pdf = doc.tobytes()
    doc.close()
    metadata = {"pmcid": "PMC123", "title": "Test study", "version": 7, "license_code": "CC BY",
                "pdf_url": CLOUD_URL + "/PMC123.7/PMC123.7.pdf"}
    listing = b'<ListBucketResult><CommonPrefixes><Prefix>PMC123.7/</Prefix></CommonPrefixes></ListBucketResult>'
    session = Session([Response(listing), Response(json.dumps(metadata).encode()), Response(pdf)])
    client = PMCClient(tmp_path, PipelineOptions("x"), session=session, sleep=lambda _: None)
    article, provenance = client.pdf_article("PMC123")
    assert article["sections"][0]["section"] == "results"
    assert provenance["version"] == 7 and provenance["format"] == "pdf"


def test_optional_index_preserves_metadata_and_normalizes(tmp_path):
    import numpy as np
    faiss = pytest.importorskip("faiss")
    class Embedder:
        def encode(self, texts, **kwargs):
            return np.array([[2, 0], [0, 3]], dtype="float32")
    chunks = [{"chunk_text": "a", "pmcid": "PMC1", "licenses": ["CC BY"]},
              {"chunk_text": "b", "pmcid": "PMC2", "provenance": {"source": "test"}}]
    result = build_index(chunks, tmp_path, Embedder())
    index = faiss.read_index(str(tmp_path / "faiss_index.index"))
    assert result["vectors"] == 2 and index.ntotal == 2
    assert np.linalg.norm(index.reconstruct(0)) == pytest.approx(1)
    metadata = json.loads((tmp_path / "chunk_metadata.json").read_text())
    assert metadata[0]["licenses"] == ["CC BY"] and metadata[1]["faiss_id"] == 1
    with pytest.raises(PipelineError, match="No usable"):
        build_index([], tmp_path, Embedder())


def test_cloud_xml_precedes_pdf(tmp_path):
    listing = b'<ListBucketResult><CommonPrefixes><Prefix>PMC123.1/</Prefix></CommonPrefixes></ListBucketResult>'
    metadata = {"pmcid": "PMC123", "version": 1, "license_code": "CC BY",
                "xml_url": CLOUD_URL + "/PMC123.1/PMC123.1.xml",
                "pdf_url": CLOUD_URL + "/PMC123.1/PMC123.1.pdf"}
    session = Session([Response(listing), Response(json.dumps(metadata).encode()), Response(xml())])
    client = PMCClient(tmp_path, PipelineOptions("x"), session=session, sleep=lambda _: None)
    article, provenance = client.pdf_article("PMC123")
    assert article["pmcid"] == "PMC123" and provenance["format"] == "jats_xml"
    assert len(session.calls) == 3 and session.calls[-1][0].endswith(".xml")


def test_backend_import_requires_no_ml_or_pdf_dependencies():
    import subprocess
    code = '''import sys
from biomedical_dataset_studio.pipeline import PipelineOptions
assert not any(m in sys.modules for m in ('torch', 'transformers', 'sentence_transformers', 'pymupdf', 'pandas', 'faiss'))
'''
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
