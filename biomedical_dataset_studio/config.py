# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Standalone configuration; generated data never points into another project."""
import os
from pathlib import Path


def get(name, default=""):
    return os.environ.get(name, default)


def path(relative):
    """Resolve outputs under the configured workspace, defaulting to ./workspace."""
    root = Path(get("BIOMEDICAL_DATASET_STUDIO_WORKSPACE").strip() or str(Path.cwd() / "workspace"))
    return root.expanduser().resolve() / relative


EMBED_MODEL = get("BIOMEDICAL_DATASET_STUDIO_EMBED_MODEL", "pritamdeka/S-PubMedBert-MS-MARCO")
