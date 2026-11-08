"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import time

import httpx

from .config import IndexerSettings

BATCH_SIZE = 16
RETRIES = 3
# nomic-embed-text is trained with a task prefix: documents use "search_document: " and the api
# uses "search_query: " for questions. Both sides must follow it or recall drops.
DOCUMENT_PREFIX = "search_document: "


def _embed_batch(client: httpx.Client, settings: IndexerSettings, batch: list[str]) -> list[list[float]]:
    url = f"{settings.ollama_url.rstrip('/')}/api/embed"
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = client.post(url, json={"model": settings.embed_model, "input": batch})
            response.raise_for_status()
            vectors = response.json()["embeddings"]
            if len(vectors) != len(batch):
                raise RuntimeError(f"asked for {len(batch)} embeddings, got {len(vectors)}")
            return [list(map(float, v)) for v in vectors]
        except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
            last = exc
            time.sleep(attempt + 1)
    raise RuntimeError(f"embedding failed after {RETRIES} attempts with model "
                       f"{settings.embed_model!r} at {url}: {last}")


def embed(
    texts: list[str],
    settings: IndexerSettings,
    *,
    client: httpx.Client | None = None,
    prefix: str = DOCUMENT_PREFIX,
) -> list[list[float]]:
    """Embed with settings.embed_model and nothing else.

    POST {ollama_url}/api/embed with {"model": ..., "input": [texts]} returns
    {"embeddings": [[...], ...]}. Texts are sent in batches of BATCH_SIZE with the task prefix,
    each batch is retried, and every vector must have the same length.
    """
    if not texts:
        return []
    owns_client = client is None
    http = client or httpx.Client(timeout=120.0)
    try:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = [prefix + t for t in texts[start:start + BATCH_SIZE]]
            vectors.extend(_embed_batch(http, settings, batch))
        dims = {len(v) for v in vectors}
        if len(dims) != 1:
            raise RuntimeError(f"embedding vectors have different lengths: {sorted(dims)}")
        return vectors
    finally:
        if owns_client:
            http.close()
