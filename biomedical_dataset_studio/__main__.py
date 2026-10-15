# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Command-line entry point: python -m biomedical_dataset_studio."""
from .pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
