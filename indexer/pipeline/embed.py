"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

from .config import IndexerSettings


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed with settings.embed_model and nothing else.

    With Ollama: POST {ollama_url}/api/embed with {"model": ..., "input": [texts]}
    returns {"embeddings": [[...], ...]}. Batch the calls; one request per chunk is slow.
    """
    # STARTER-TODO(3.1): implement embedding.
    raise NotImplementedError("embed: see STARTER-TODO(3.1)")
