# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Required PMC/JATS metadata helpers; no fixed-query collection script."""
import re
import html

BASE_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def strip_namespace(elem):
    for el in elem.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def normalize(text):
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def text(elem):
    if elem is None:
        return ""
    return normalize("".join(elem.itertext()))


def get_title(article):
    return text(article.find(".//article-title"))


def get_journal(article):
    return text(article.find(".//journal-title"))


def get_pmid(article):
    for aid in article.findall(".//article-id"):
        if aid.attrib.get("pub-id-type") == "pmid":
            return text(aid)
    return ""
