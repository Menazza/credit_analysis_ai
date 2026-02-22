"""
Generate embeddings for note chunks via OpenAI. Used for semantic search.
"""
from __future__ import annotations

from typing import Sequence

from app.config import get_settings


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def get_embeddings(texts: Sequence[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts. Returns list of vectors.
    Skips API call if OPENAI_API_KEY not set; returns empty lists.
    """
    settings = get_settings()
    if not settings.openai_api_key or not texts:
        return [[] for _ in texts]

    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    # API accepts max 2048 inputs per request; we batch
    batch_size = 100
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[t[:8000] for t in batch],  # limit input length
        )
        for d in resp.data:
            all_embeddings.append(d.embedding)
    return all_embeddings


def get_embedding(text: str) -> list[float]:
    """Single text embedding."""
    out = get_embeddings([text])
    return out[0] if out else []
