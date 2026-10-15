# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Standalone, CPU-friendly dataset acquisition and processing (no UI or LLM)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import config, chunking
from .pmc_xml import BASE_EUTILS, get_journal, get_pmid, get_title, strip_namespace, text

OAI_URL = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
CLOUD_URL = "https://pmc-oa-opendata.s3.amazonaws.com"
PIPELINE_VERSION = "1.0.1"


class PipelineError(RuntimeError):
    """Actionable acquisition or processing failure."""


class PipelineCancelled(BaseException):
    """Cooperative stop signal; not swallowed by per-article failure handling."""


@dataclass(frozen=True)
class PipelineOptions:
    query: str
    article_limit: int = 20
    chunk_size: int = 500
    chunk_overlap: int = 100
    pdf_fallback: bool = False
    cache_ttl: float = 86400
    retries: int = 3
    timeout: float = 30
    request_interval: float = 0.34

    def __post_init__(self):
        if not self.query.strip():
            raise ValueError("A non-empty biomedical search query is required.")
        if type(self.article_limit) is not int or not 1 <= self.article_limit <= 10000:
            raise ValueError("article_limit must be an integer between 1 and 10000 (ESearch limit).")
        if type(self.chunk_size) is not int or type(self.chunk_overlap) is not int or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("Require integer chunk_size > chunk_overlap >= 0.")
        if type(self.retries) is not int or self.retries < 0:
            raise ValueError("retries must be a non-negative integer.")
        if any(not math.isfinite(v) for v in (self.timeout, self.cache_ttl, self.request_interval)) or self.timeout <= 0 or min(self.cache_ttl, self.request_interval) < 0:
            raise ValueError("timeout must be positive; cache_ttl and request_interval must be non-negative finite numbers.")


def clean_text(value):
    """Conservative XML cleanup: retain biomedical symbols, URLs and numbers."""
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\ufeff]", " ", value)
    return chunking.clean_chunk_text(value)


def _prose_text(element):
    """Keep block boundaries while preserving intentional inline word fragments."""
    block_tags = {"p", "list", "list-item", "title", "sec", "boxed-text", "disp-quote"}
    def render(node):
        parts = [node.text or ""]
        for child in node:
            value = render(child)
            parts.append(f" {value} " if child.tag in block_tags else value)
            parts.append(child.tail or "")
        return "".join(parts)
    return clean_text(render(element))


def parse_xml(payload, expected_pmcid):
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PipelineError(f"Invalid full-text XML for {expected_pmcid}: {exc}") from exc
    strip_namespace(root)
    error = root.find(".//error")
    if error is not None:
        raise PipelineError(f"PMC full-text unavailable: {error.get('code', '')}: {text(error)}")
    article = root if root.tag == "article" else root.find(".//article")
    if article is None:
        raise PipelineError("Response contains no JATS article.")
    front = article.find("front/article-meta")
    if front is None:
        raise PipelineError("JATS article is missing article metadata.")
    ids = {node.get("pub-id-type"): text(node) for node in front.findall("article-id")}
    pmcid = ids.get("pmcid", ids.get("pmc", ""))
    pmcid = pmcid.upper() if pmcid.upper().startswith("PMC") else "PMC" + pmcid
    if pmcid != expected_pmcid:
        raise PipelineError(f"Article identifier mismatch: requested {expected_pmcid}, received {pmcid}.")
    title = clean_text(get_title(article))
    if not title:
        raise PipelineError("JATS article has no title.")
    licenses = []
    for node in front.findall(".//license"):
        licenses.append({"url": node.get("{http://www.w3.org/1999/xlink}href", ""),
                         "type": node.get("license-type", ""), "text": clean_text(text(node))})
    for node in front.findall(".//license_ref"):
        licenses.append({"url": text(node), "type": "", "text": ""})
    authors = []
    for node in front.findall(".//contrib[@contrib-type='author']"):
        name = node.find("name")
        value = clean_text(f"{text(name.find('given-names'))} {text(name.find('surname'))}") if name is not None else text(node.find("collab"))
        if value:
            authors.append(value)
    sections = []
    def abstract_paragraphs(node):
        if node.tag == "p":
            return [_prose_text(node)]
        return [value for child in node for value in abstract_paragraphs(child)]
    for i, node in enumerate(front.findall("abstract")):
        sections.append({"section_id": f"abstract-{i + 1}", "section": "abstract", "heading": text(node.find("title")),
                         "paragraphs": abstract_paragraphs(node) or [_prose_text(node)]})

    def walk(container, path, heading="", section="body"):
        paragraphs = []
        def flush():
            if paragraphs:
                sections.append({"section_id": f"{path}-{len(sections) + 1}", "section": section,
                                 "heading": heading, "paragraphs": list(paragraphs)})
                paragraphs.clear()
        for i, child in enumerate(container):
            if child.tag == "sec":
                flush()
                label = clean_text(text(child.find("title"))) or child.get("sec-type", "body")
                walk(child, f"{path}/{child.get('id', str(i))}", label, label.lower())
            elif child.tag in {"p", "list", "disp-quote", "boxed-text"}:
                # Avoid collecting embedded table/figure/supplement captions as prose.
                clone = ET.fromstring(ET.tostring(child))
                for parent in clone.iter():
                    for excluded in list(parent):
                        if excluded.tag in {"table-wrap", "fig", "supplementary-material", "ref-list"}:
                            tail = excluded.tail or ""
                            excluded.clear()
                            excluded.tail = tail
                value = _prose_text(clone)
                if value:
                    paragraphs.append(value)
        flush()
    body = article.find("body")
    if body is not None:
        walk(body, "body")
    for section in sections:
        section["text"] = " ".join(section["paragraphs"])
    if not any(s["text"] for s in sections if s["section"] != "abstract"):
        raise PipelineError("No readable full-text body; abstract-only records are not datasets.")
    return {"pmcid": pmcid, "pmid": get_pmid(article), "doi": ids.get("doi", ""), "title": title,
            "journal": clean_text(get_journal(article)), "year": text(front.find("pub-date/year")),
            "authors": authors, "keywords": [text(n) for n in front.findall(".//kwd")],
            "article_type": article.get("article-type", ""), "licenses": licenses,
            "source_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/", "sections": sections}


def chunk_article(article, options):
    """Reuse historical windows/filters; deduplicate within an article to retain attribution."""
    chunks, seen = [], set()
    for section in article["sections"]:
        if section["section"] in chunking.SKIP_SECTIONS:
            continue
        for i, value in enumerate(chunking.split_text_into_chunks(section["text"], options.chunk_size, options.chunk_overlap)):
            if chunking.is_table_heavy(value) or chunking.is_low_information_chunk(value):
                continue
            fingerprint = chunking.normalize_for_duplicate_check(value)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            chunks.append({k: article[k] for k in ("pmcid", "pmid", "doi", "title", "journal", "year", "authors", "keywords", "licenses", "source_url", "provenance")})
            chunks[-1].update(chunk_id=f"{article['pmcid']}_{hashlib.sha256(section['section_id'].encode()).hexdigest()[:12]}_{i + 1:04d}",
                              section=section["section"], section_id=section["section_id"], chunk_index=i + 1,
                              word_start=i * (options.chunk_size - options.chunk_overlap),
                              word_end=i * (options.chunk_size - options.chunk_overlap) + len(value.split()), chunk_text=value)
    return chunks


class PMCClient:
    """Supported PMC HTTP services, disk cache, bounded retries and polite pacing."""
    def __init__(self, cache_dir, options, emit=None, session=None, sleep=time.sleep):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.options, self.emit = options, emit or (lambda **event: None)
        self.session, self.sleep = session or requests.Session(), sleep
        self.owns_session = session is None
        self.last_request = 0.0

    def close(self):
        if self.owns_session:
            self.session.close()

    def get(self, url, params=None):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in {"eutils.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov", "pmc-oa-opendata.s3.amazonaws.com"}:
            raise PipelineError("Refusing download outside official PMC services.")
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        cached = self.cache_dir / f"{key}.json"
        if cached.exists() and time.time() - cached.stat().st_mtime < self.options.cache_ttl:
            try:
                entry = json.loads(cached.read_text(encoding="utf8"))
                payload = bytes.fromhex(entry["payload"])
                if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise ValueError("Cache checksum mismatch")
                self.emit(stage="cache_hit", source_url=url)
                return payload, dict(entry["provenance"], cache_hit=True)
            except (ValueError, KeyError, TypeError):
                self.emit(stage="cache_invalid", source_url=url)
        for attempt in range(self.options.retries + 1):
            self.sleep(max(0, max(0.34, self.options.request_interval) - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            response = None
            try:
                response = self.session.get(url, params=params, timeout=self.options.timeout, allow_redirects=False,
                                            headers={"Accept-Encoding": "gzip, deflate", "User-Agent": "BiomedicalDatasetStudio/1.0"})
                if response.status_code >= 300 and response.status_code < 400:
                    raise PipelineError("Unexpected redirect from official PMC service.")
                response.raise_for_status()
                payload = response.content
                # Do not store contact addresses or API keys in provenance.
                public_params = {k: v for k, v in (params or {}).items() if k not in {"email", "api_key"}}
                provenance = {"source_url": url, "request_params": public_params,
                              "retrieved_at": datetime.now(timezone.utc).isoformat(),
                              "sha256": hashlib.sha256(payload).hexdigest(), "etag": response.headers.get("ETag", ""),
                              "last_modified": response.headers.get("Last-Modified", ""), "cache_hit": False}
                entry = {"payload": payload.hex(), "sha256": provenance["sha256"], "provenance": provenance}
                temporary = cached.with_suffix(f".{uuid.uuid4().hex}.tmp")
                temporary.write_text(json.dumps(entry), encoding="utf8")
                temporary.replace(cached)
                return payload, provenance
            except requests.RequestException as exc:
                status = response.status_code if response is not None else None
                if status is not None and status not in {408, 429} and status < 500:
                    raise PipelineError(f"PMC request failed: HTTP {status} at {url}.") from exc
                if attempt == self.options.retries:
                    raise PipelineError(f"PMC request failed after {attempt + 1} attempts at {url}; check network/service availability.") from exc
                delay = min(60, 2 ** attempt)
                retry_after = response.headers.get("Retry-After", "") if response is not None else ""
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    try:
                        delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                    except (ValueError, TypeError, OverflowError):
                        pass
                self.emit(stage="retry", attempt=attempt + 1, delay=delay, source_url=url)
                self.sleep(delay)

    def discover(self):
        result, start = [], 0
        query = f"({self.options.query}) AND open_access[filter] NOT pmc embargo[filter]"
        while len(result) < self.options.article_limit:
            params = {"db": "pmc", "term": query, "retmode": "json", "sort": "relevance",
                      "retstart": start, "retmax": min(500, self.options.article_limit - len(result)), "tool": "biomedical_dataset_studio"}
            for key, env in (("email", "NCBI_EMAIL"), ("api_key", "NCBI_API_KEY")):
                if config.get(env):
                    params[key] = config.get(env)
            payload, _ = self.get(f"{BASE_EUTILS}/esearch.fcgi", params)
            try:
                data = json.loads(payload)
                if "error" in data:
                    raise ValueError(str(data["error"]))
                search = data["esearchresult"]
                if search.get("ERROR") or search.get("errorlist"):
                    raise ValueError(str(search.get("ERROR") or search["errorlist"]))
                ids = search["idlist"]
                count = int(search["count"])
                if not isinstance(ids, list) or any(not re.fullmatch(r"\d+", str(i)) for i in ids):
                    raise ValueError("Invalid PMC identifier list")
            except (ValueError, KeyError, TypeError) as exc:
                raise PipelineError(f"Invalid PMC search response: {exc}") from exc
            result.extend("PMC" + str(i) for i in ids)
            start += len(ids)
            if not ids or start >= min(count, 10000):
                break
        return list(dict.fromkeys(result))[:self.options.article_limit]

    def fetch_xml(self, pmcid):
        return self.get(OAI_URL, {"verb": "GetRecord", "identifier": f"oai:pubmedcentral.nih.gov:{pmcid[3:]}", "metadataPrefix": "pmc"})

    def pdf_article(self, pmcid):
        """PDF only from current Cloud metadata and conservative, explicit reuse licenses."""
        prefixes, token = [], ""
        while True:
            params = {"list-type": "2", "prefix": pmcid + ".", "delimiter": "/"}
            if token:
                params["continuation-token"] = token
            payload, _ = self.get(CLOUD_URL, params)
            root = ET.fromstring(payload)
            strip_namespace(root)
            prefixes.extend(text(n) for n in root.findall("CommonPrefixes/Prefix"))
            if text(root.find("IsTruncated")) != "true":
                break
            next_token = text(root.find("NextContinuationToken"))
            if not next_token or next_token == token:
                raise PipelineError("PMC Cloud listing pagination token is missing or repeated.")
            token = next_token
        failures = []
        # Select first eligible version deterministically; do not claim highest means newest.
        for prefix in sorted(prefixes):
            if not re.fullmatch(re.escape(pmcid) + r"\.\d+/", prefix):
                continue
            try:
                payload, metadata_provenance = self.get(f"{CLOUD_URL}/{prefix}{prefix[:-1]}.json")
                metadata = json.loads(payload)
                if str(metadata.get("pmcid")) != pmcid:
                    raise PipelineError("Cloud metadata identifier mismatch.")
                # Cloud XML takes precedence even if the OAI record was unavailable.
                xml_url = metadata.get("xml_url", "")
                if xml_url:
                    parsed_xml = urlparse(xml_url)
                    if parsed_xml.netloc != "pmc-oa-opendata.s3.amazonaws.com" or not parsed_xml.path.startswith("/" + prefix):
                        raise PipelineError("Cloud XML URL does not match the article version.")
                    try:
                        xml_payload, xml_provenance = self.get(xml_url)
                        article = parse_xml(xml_payload, pmcid)
                        xml_provenance.update(format="jats_xml", version=metadata.get("version"),
                                              cloud_metadata=metadata, metadata_provenance=metadata_provenance)
                        return article, xml_provenance
                    except (PipelineError, ValueError) as exc:
                        failures.append(f"Cloud XML: {exc}")
                license_code = str(metadata.get("license_code", "")).upper()
                if license_code not in {"CC0", "CC BY", "CC BY-SA", "CC-BY", "CC-BY-SA"}:
                    raise PipelineError(f"PDF fallback excluded by license policy: {license_code or 'unknown'}.")
                if str(metadata.get("is_retracted", "")).lower() in {"yes", "true", "1"}:
                    raise PipelineError("Retracted Cloud version excluded.")
                pdf_url = metadata.get("pdf_url", "")
                if not pdf_url:
                    raise PipelineError("No publisher-permitted PDF in Cloud metadata.")
                # Metadata URLs must identify this exact article version in the official bucket.
                parsed = urlparse(pdf_url)
                if parsed.netloc != "pmc-oa-opendata.s3.amazonaws.com" or not parsed.path.startswith("/" + prefix):
                    raise PipelineError("Cloud PDF URL does not match the article version.")
                pdf, provenance = self.get(pdf_url)
                if not pdf.startswith(b"%PDF"):
                    raise PipelineError("Cloud response is not a PDF.")
                from .pdf_processing import normalize_text, split_into_sections
                import pymupdf
                with pymupdf.open(stream=pdf, filetype="pdf") as document:
                    extracted = "\n".join(page.get_text("text") for page in document)
                sections = split_into_sections(normalize_text(extracted))
                if not sections:
                    raise PipelineError("PDF contains no readable text; OCR is not enabled.")
                for i, section in enumerate(sections):
                    section.update(section_id=f"pdf-{i + 1}", heading=section["section"], paragraphs=[section["text"]])
                article = {"pmcid": pmcid, "pmid": str(metadata.get("pmid", "")), "doi": metadata.get("doi", ""),
                           "title": clean_text(metadata.get("title", "")), "journal": "", "year": "", "authors": [], "keywords": [],
                           "article_type": "", "licenses": [{"type": license_code, "url": "", "text": ""}],
                           "source_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/", "sections": sections}
                if not article["title"]:
                    raise PipelineError("Cloud metadata has no title.")
                provenance.update(format="pdf", version=metadata.get("version"), cloud_metadata=metadata,
                                  metadata_provenance=metadata_provenance)
                return article, provenance
            except Exception as exc:
                failures.append(str(exc))
        raise PipelineError("No eligible PDF fallback: " + ("; ".join(failures) or "no Cloud versions found"))


def build_index(chunks, destination, embedder=None):
    """Optional normalized CPU embeddings; reuse historical FAISS construction."""
    if not chunks:
        raise PipelineError("No usable chunks to index.")
    import numpy as np
    import faiss
    from .indexing import create_faiss_index
    if embedder is None:
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer(config.EMBED_MODEL, device="cpu")
    vectors = np.asarray(embedder.encode([c["chunk_text"] for c in chunks], convert_to_numpy=True, normalize_embeddings=True), dtype="float32")
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or vectors.shape[1] == 0 or not np.isfinite(vectors).all():
        raise PipelineError("Embedding output must contain one finite vector per chunk.")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if (norms == 0).any():
        raise PipelineError("Embedding output contains zero vectors.")
    vectors = np.ascontiguousarray(vectors / norms)
    index = create_faiss_index(vectors)
    faiss.write_index(index, str(destination / "faiss_index.index"))
    (destination / "chunk_metadata.json").write_text(json.dumps([dict(c, faiss_id=i) for i, c in enumerate(chunks)], ensure_ascii=False), encoding="utf8")
    return {"vectors": index.ntotal, "dimension": vectors.shape[1], "model": config.EMBED_MODEL if type(embedder).__name__ == "SentenceTransformer" else type(embedder).__name__, "normalized": True}


def _export_records(run_dir, articles, chunks, failures, duplicates):
    """Write the same datasets for completed and cooperatively interrupted runs."""
    for name, records in (("articles", articles), ("chunks", chunks), ("failures", failures), ("duplicates", duplicates)):
        with (run_dir / f"{name}.jsonl").open("w", encoding="utf8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    metadata = [{k: v for k, v in a.items() if k != "sections"} for a in articles]
    (run_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf8")
    fields = ["pmcid", "pmid", "doi", "title", "journal", "year", "authors", "keywords", "article_type", "licenses", "source_url", "provenance"]
    with (run_dir / "metadata.csv").open("w", encoding="utf8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in a.items()} for a in metadata)


def run_pipeline(options, output_root=None, on_progress=None, *, client=None, index=False, embedder=None):
    """Create an isolated run; return its manifest. Limit counts discovered candidates."""
    root = Path(output_root) if output_root is not None else config.path("dataset_studio")
    run_dir = root / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12])
    run_dir.mkdir(parents=True, exist_ok=False)
    events = run_dir / "progress.jsonl"
    def emit(**event):
        event = dict(timestamp=datetime.now(timezone.utc).isoformat(), **event)
        with events.open("a", encoding="utf8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        if on_progress:
            on_progress(event)
    owned = client is None
    client = client or PMCClient(root / "cache", options, emit)
    articles, chunks, failures, duplicates = [], [], [], []
    manifest = {"pipeline_version": PIPELINE_VERSION, "options": asdict(options), "run_dir": str(run_dir.resolve()),
                "status": "running", "source": "NCBI PMC", "discovered": 0,
                "cache_notice": "Cached source snapshots may differ from current PMC content; see retrieved_at and cache_hit."}
    try:
        emit(stage="run_started", run_dir=str(run_dir.resolve()))
        emit(stage="discovery", query=options.query)
        ids = client.discover()
        manifest["discovered"] = len(ids)
        seen_ids, seen_articles = set(), {}
        for completed, pmcid in enumerate(ids, 1):
            if pmcid in seen_ids:
                duplicates.append({"pmcid": pmcid, "reason": "identifier"})
                continue
            seen_ids.add(pmcid)
            emit(stage="article_started", pmcid=pmcid, completed=completed - 1, total=len(ids))
            try:
                xml_failure = ""
                try:
                    payload, provenance = client.fetch_xml(pmcid)
                    article = parse_xml(payload, pmcid)
                    provenance = dict(provenance, format="jats_xml")
                except (PipelineError, ValueError) as exc:
                    if not options.pdf_fallback:
                        raise
                    xml_failure = str(exc)
                    emit(stage="pdf_fallback", pmcid=pmcid, reason=xml_failure)
                    article, provenance = client.pdf_article(pmcid)
                article["provenance"] = dict(provenance, pipeline_version=PIPELINE_VERSION, query=options.query,
                    processed_at=datetime.now(timezone.utc).isoformat(), xml_failure=xml_failure,
                    cleaning="NFKC and whitespace; JATS prose with block boundaries", chunk_size=options.chunk_size, chunk_overlap=options.chunk_overlap)
                fingerprint = hashlib.sha256(" ".join(s["text"].lower() for s in article["sections"]).encode()).hexdigest()
                if fingerprint in seen_articles:
                    duplicates.append({"pmcid": pmcid, "duplicate_of": seen_articles[fingerprint], "reason": "identical_text",
                                       "provenance": article["provenance"], "licenses": article["licenses"]})
                    emit(stage="article_duplicate", pmcid=pmcid, duplicate_of=seen_articles[fingerprint])
                else:
                    article_chunks = chunk_article(article, options)
                    seen_articles[fingerprint] = pmcid
                    articles.append(article)
                    chunks.extend(article_chunks)
                    emit(stage="article_completed", pmcid=pmcid, chunks=len(article_chunks), completed=completed, total=len(ids))
            except Exception as exc:
                failures.append({"pmcid": pmcid, "error": str(exc), "error_type": type(exc).__name__})
                emit(stage="article_failed", pmcid=pmcid, error=str(exc), completed=completed, total=len(ids))
        _export_records(run_dir, articles, chunks, failures, duplicates)
        manifest.update(articles=len(articles), chunks=len(chunks), failures=len(failures), duplicates=len(duplicates),
                        status="partial" if failures else "complete")
        if index:
            emit(stage="index_started", chunks=len(chunks))
            try:
                manifest["index"] = build_index(chunks, run_dir, embedder)
            except Exception as exc:
                manifest.update(status="partial", index_error=f"{type(exc).__name__}: {exc}")
                emit(stage="index_failed", error=manifest["index_error"])
        emit(stage="complete", articles=len(articles), chunks=len(chunks), failures=len(failures))
    except (PipelineCancelled, KeyboardInterrupt) as exc:
        manifest.update(status="interrupted", error=str(exc) or "Processing stopped by the user.")
        _export_records(run_dir, articles, chunks, failures, duplicates)
        emit(stage="interrupted", error=manifest["error"])
        raise
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        emit(stage="failed", error=manifest["error"])
        raise
    finally:
        manifest.update(articles=len(articles), chunks=len(chunks), failures=len(failures), duplicates=len(duplicates))
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
        if owned:
            client.close()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pdf-fallback", action="store_true")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--overlap", type=int, default=100)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        options = PipelineOptions(args.query, args.limit, args.chunk_size, args.overlap, args.pdf_fallback,
                                  cache_ttl=0 if args.refresh else 86400)
        manifest = run_pipeline(options, args.output, lambda event: print(json.dumps(event)), index=args.index)
        print(json.dumps(manifest, indent=2))
        return 0 if manifest["status"] == "complete" else 1
    except (PipelineError, ValueError, OSError) as exc:
        parser.exit(2, f"Dataset Studio: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
