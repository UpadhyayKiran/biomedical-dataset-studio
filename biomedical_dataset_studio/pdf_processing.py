# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Validated PDF text cleanup and heading heuristics; XML remains preferred."""
import re

def normalize_text(text):
    if not text:
        return ""

    text = text.replace("\r", "\n")

    replacements = {
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\xa0": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\b[aA]1{5,}\b", " ", text)
    text = re.sub(r"(?m)^\s*\d+\s*$", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def cleanup_section_text(text):
    if not text:
        return ""

    junk_prefixes = [
        "open access",
        "citation:",
        "editor:",
        "received:",
        "accepted:",
        "published:",
        "copyright:",
        "data availability statement:",
        "funding:",
        "competing interests:",
    ]

    cleaned = []

    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()

        if not stripped:
            continue

        if any(lower.startswith(p) for p in junk_prefixes):
            continue

        if re.match(r"^https?://doi\.org/", lower):
            continue

        if re.match(r"^(fig|figure|table)\s*\d+", lower):
            continue

        # Remove repeated running headers inside sections
        if re.search(r"costs of ct with anticancer biologic agents", lower):
            continue

        if "using the abc methodology" in lower and "cancer center" in lower:
            continue

        # Remove table-like noisy rows
        if len(re.findall(r"\d+", stripped)) > 12 and len(stripped.split()) > 12:
            continue

        # Remove noisy all-caps table headers
        if stripped.isupper() and len(stripped.split()) > 10:
            continue

        cleaned.append(stripped)

    text = "\n".join(cleaned)

    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


SECTION_PATTERNS = {
    "abstract": [
        r"^\s*(\d+\.?\s*)?abstract\s*$",
    ],
    "introduction": [
        r"^\s*(\d+\.?\s*)?introduction\s*$",
        r"^\s*(\d+\.?\s*)?background\s*$",
    ],
    "methods": [
        r"^\s*(\d+\.?\s*)?methods\s*$",
        r"^\s*(\d+\.?\s*)?materials and methods\s*$",
        r"^\s*(\d+\.?\s*)?methodology\s*$",
        r"^\s*(\d+\.?\s*)?patients and methods\s*$",
        r"^\s*(\d+\.?\s*)?study design\s*$",
    ],
    "results": [
        r"^\s*(\d+\.?\s*)?results\s*$",
        r"^\s*(\d+\.?\s*)?findings\s*$",
    ],
    "discussion": [
        r"^\s*(\d+\.?\s*)?discussion\s*$",
    ],
    "conclusion": [
        r"^\s*(\d+\.?\s*)?conclusion[s]?\s*$",
        r"^\s*(\d+\.?\s*)?concluding remarks\s*$",
    ],
    "acknowledgments": [
        r"^\s*acknowledg?ments?\s*$",
    ],
    "references": [
        r"^\s*references\s*$",
        r"^\s*bibliography\s*$",
    ],
    "supplementary": [
        r"^\s*supporting information\s*$",
        r"^\s*supplementary information\s*$",
        r"^\s*supplementary material[s]?\s*$",
    ],
    "author_contributions": [
        r"^\s*author contributions\s*$",
        r"^\s*contributions\s*$",
    ],
}


def identify_heading(line):
    stripped = line.strip()

    if len(stripped.split()) > 8:
        return None

    for section, patterns in SECTION_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, stripped, flags=re.IGNORECASE):
                return section

    return None


def split_into_sections(text):
    sections = []
    current_section = "unknown"
    buffer = []

    for line in text.splitlines():
        detected = identify_heading(line)

        if detected:
            section_text = "\n".join(buffer).strip()

            if section_text:
                sections.append(
                    {
                        "section": current_section,
                        "text": cleanup_section_text(section_text),
                    }
                )

            current_section = detected
            buffer = []
        else:
            buffer.append(line)

    section_text = "\n".join(buffer).strip()

    if section_text:
        sections.append(
            {
                "section": current_section,
                "text": cleanup_section_text(section_text),
            }
        )

    return [s for s in sections if s["text"].strip()]
