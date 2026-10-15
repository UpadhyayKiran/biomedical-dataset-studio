<!-- SPDX-FileCopyrightText: 2026 Kiran Upadhyay -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Licensing and attribution audit — 15 October 2026

## Repository source and authorization

The maintainer expressly requested this standalone extraction, Apache-2.0 licensing and publication under `UpadhyayKiran/biomedical-dataset-studio`, with copyright attribution to Kiran Upadhyay, 2026. The source project's licensing/attribution records contain the maintainer's declaration of independent implementation and ownership of the selected source. No concrete third-party source claim, inherited copyright notice or applicable publication restriction was identified in the selected files. This is the authorization basis for licensing this extraction; it is not a legal determination about unprovided agreements.

Only the Studio pipeline/UI/support, required helper functions, synthetic tests and newly prepared standalone documentation are included. Academic reports, institutional materials, other people's personal information, historical results, datasets, model weights and the original Git history are excluded. `SOURCE_PROVENANCE.json` records the exact source files, hashes, selected functions and extraction changes. No third-party code ownership is inferred from report authorship or an installed dependency.

The `LICENSE` file is downloaded byte-for-byte from the Apache Software Foundation's official license text. Its appendix placeholders remain unmodified; actual copyright attribution appears in SPDX headers and `NOTICE`. No upstream third-party source is vendored. `NOTICE` records the project's attribution and the separation of dependency/article/model terms.

## Dependency compatibility

The direct default runtime dependencies, Requests and Streamlit, use Apache-2.0. Their transitive packages retain their own terms; release-environment package metadata is recorded separately in `DEPENDENCIES.json`. MIT/BSD/Apache-style package licenses are permissive but still require preserving applicable notices when redistributing their code/binaries. Certifi's MPL-2.0 is a file-level copyleft license; it is not relicensed by this repository. Optional native wheels can bundle additional components whose notices remain part of their upstream distributions.

**Optional PDF:** PyMuPDF/MuPDF is offered under AGPL or a commercial agreement by Artifex. It is deliberately excluded from the default dependency set and no PyMuPDF source or binary is bundled. This repository's Apache-2.0 grant does not remove AGPL obligations from an application combined with the AGPL component. If enabling or redistributing that combination, comply with the applicable AGPL source/network/notice obligations, or obtain suitable commercial rights from Artifex. Do not represent the combined PDF-enabled distribution as Apache-only. This source distribution grants no commercial PyMuPDF license.

Apache-2.0 source may be used in a GPLv3/AGPLv3-governed combination subject to those licenses; compatibility does not make the copyleft component permissively licensed. See [Apache's compatibility explanation](https://www.apache.org/licenses/GPL-compatibility), [GNU's compatibility discussion](https://www.gnu.org/licenses/license-compatibility.en.html), [PyMuPDF's license documentation](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) and [Artifex licensing](https://artifex.com/licensing).

**Optional indexing:** NumPy and FAISS have permissive package licenses; Sentence Transformers and Transformers use Apache-2.0, and PyTorch has BSD-style terms. Their dependencies and bundled components retain their original terms. No weights or package binaries are redistributed here. Model licensing is independent: the configured `pritamdeka/S-PubMedBert-MS-MARCO` [model card](https://huggingface.co/pritamdeka/S-PubMedBert-MS-MARCO) declares **CC BY-NC 2.0**. It is not a generally commercial-use-authorized default. Configure an appropriately licensed model for your use and preserve its attribution.

Installing dependencies is not copying their copyright into Kiran Upadhyay's ownership. The dependency inventory is an environment-specific audit, not a universal license clearance or a reproducible lockfile for all platforms and future resolver choices. Recheck terms when changing versions or distributing an executable/container with dependencies.

## Biomedical articles

Downloaded biomedical articles, their original text, metadata and derived chunks retain their respective licenses and attribution obligations. They are **not covered by this software's Apache-2.0 license**. An OA filter is not a grant of unrestricted commercial reuse. Original licenses and provenance are included in exports; publication/redistribution must follow article-specific terms. Nothing is acquired or bundled merely because the software is open source.

PMC source snapshots can change or be withdrawn. Local exported datasets explicitly warn that cached content may be stale. Refer to [PMC's reuse guidance](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/).

## Patent statement

No patent ownership or patentability is claimed. Apache-2.0 includes the patent license and termination terms stated in its official text; it does not transfer patent ownership or establish that an invention is patented.
