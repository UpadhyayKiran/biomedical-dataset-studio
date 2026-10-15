# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Validated word windows, filters and exact duplicate fingerprints."""
import hashlib

MIN_CHUNK_WORDS = 60


MIN_ALPHA_WORDS = 40


SKIP_SECTIONS = {
    "title",
    "references",
    "supplementary",
    "acknowledgments",
    "author_contributions",
}


def clean_chunk_text(text):
    if not text:
        return ""

    text = str(text)
    text = " ".join(text.split())
    return text.strip()


def split_text_into_chunks(text, chunk_size=500, overlap=100):
    words = text.split()

    if len(words) <= chunk_size:
        return [" ".join(words)]

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))

        if end >= len(words):
            break

        start = end - overlap

    return chunks


def is_table_heavy(text):
    words = text.split()

    if len(words) < 40:
        return True

    numeric_tokens = sum(1 for w in words if any(ch.isdigit() for ch in w))
    numeric_ratio = numeric_tokens / max(len(words), 1)

    return numeric_ratio > 0.35


def is_low_information_chunk(text):
    words = text.split()

    if len(words) < MIN_CHUNK_WORDS:
        return True

    alphabetic_words = [
        w for w in words
        if any(ch.isalpha() for ch in w)
    ]

    if len(alphabetic_words) < MIN_ALPHA_WORDS:
        return True

    return False


def normalize_for_duplicate_check(text):
    normalized = text.lower().strip()
    normalized = " ".join(normalized.split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()
