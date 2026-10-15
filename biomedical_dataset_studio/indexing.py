# SPDX-FileCopyrightText: 2026 Kiran Upadhyay
# SPDX-License-Identifier: Apache-2.0

"""Optional normalized inner-product FAISS construction."""
import faiss

def create_faiss_index(embeddings):
    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    print(f"FAISS index created with {index.ntotal} vectors.")
    return index
