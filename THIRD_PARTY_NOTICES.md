<!-- SPDX-FileCopyrightText: 2026 Kiran Upadhyay -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Third-party notices

No third-party package source, binaries, model weights or biomedical article bodies are vendored in this source repository. Dependencies are installed from their upstream distributions and retain their authors' copyright notices and licenses. This file summarizes important terms; preserve the full upstream notices if redistributing those components. See the [licensing audit](docs/LICENSING.md) and [release-environment inventory](docs/DEPENDENCIES.json).

| Component | Upstream license / attribution source | Treatment |
| --- | --- | --- |
| Requests | [Apache-2.0; Requests contributors](https://github.com/psf/requests/blob/main/LICENSE) | Default dependency; retain upstream license/notices if redistributed. |
| Streamlit | [Apache-2.0; Streamlit/Snowflake contributors](https://github.com/streamlit/streamlit/blob/develop/LICENSE) | Default dependency; upstream frontend/native dependencies retain their own terms. |
| NumPy | [BSD-3-Clause; NumPy Developers](https://github.com/numpy/numpy/blob/main/LICENSE.txt) | Used by optional indexing and indirectly by Streamlit; native wheel notices also apply. |
| FAISS | [MIT; Meta Platforms and contributors](https://github.com/facebookresearch/faiss/blob/main/LICENSE) | Optional CPU index dependency; no native wheel bundled here. |
| Sentence Transformers | [Apache-2.0; upstream contributors](https://github.com/huggingface/sentence-transformers/blob/master/LICENSE) | Optional embedding library, not the model-weight license. |
| Transformers | [Apache-2.0; Hugging Face and contributors](https://github.com/huggingface/transformers/blob/main/LICENSE) | Optional embedding stack; no generation/LLM feature. |
| PyTorch | [BSD-style; PyTorch contributors and included notices](https://github.com/pytorch/pytorch/blob/main/LICENSE) | Optional transitive dependency; use CPU execution. |
| PyMuPDF / MuPDF | [AGPL or commercial; Artifex and upstream authors](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) | Optional PDF dependency only; **not Apache-2.0**. Combined deployments/distributions must satisfy applicable AGPL requirements or separately licensed commercial terms. |
| pytest | [MIT; pytest contributors](https://github.com/pytest-dev/pytest/blob/main/LICENSE) | Development/test dependency. |
| certifi | [MPL-2.0; certifi contributors and CA data terms](https://github.com/certifi/python-certifi/blob/master/LICENSE) | Transitive Requests dependency; retain its file-level terms/notices. |
| S-PubMedBert-MS-MARCO | [CC BY-NC 2.0; pritamdeka model card](https://huggingface.co/pritamdeka/S-PubMedBert-MS-MARCO) | Optional configured model; **weights not included**, noncommercial terms remain applicable. |
| PMC articles | [Respective article authors/publishers and per-article licenses](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/) | Downloaded article content and derived datasets are **not licensed by this software repository**. |

Other transitive dependencies and their license metadata appear in the environment inventory. Installing a component does not transfer ownership of it to the Studio's author. Mentioning a project does not imply endorsement.
