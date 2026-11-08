"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

from typing import Any

from .config import IndexerSettings
from .models import Chunk


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count."""
    # STARTER-TODO(3.1, 4.4): implement storing. Decide what happens to the old index
    # while the API is serving from it, and write that decision into ADR 0001.
    raise NotImplementedError("store: see STARTER-TODO(3.1, 4.4)")
