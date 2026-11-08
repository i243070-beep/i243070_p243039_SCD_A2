"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .config import IndexerSettings
from .models import Chunk

ADD_BATCH = 100


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def store(
    chunks: list[Chunk],
    vectors: list[list[float]],
    settings: IndexerSettings,
    client: Any | None = None,
) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model and vector
    dimension in the collection metadata (section 4.4). Return the count.

    What happens to the old index while the API is serving from it (ADR 0001): the new index is
    built under a temporary name and only swapped in once it is complete and counted. If anything
    fails, the temporary collection is deleted and the old index keeps serving. The metadata also
    carries an `index_id` that changes on every build; the api keys its semantic cache by it, so a
    re-index invalidates the cache without the indexer ever talking to Redis.
    """
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    if not chunks:
        raise ValueError("refusing to replace the index with an empty one")
    dims = {len(v) for v in vectors}
    if len(dims) != 1:
        raise ValueError(f"vectors have different lengths: {sorted(dims)}")
    ids = [c.id for c in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("chunk ids are not unique")

    client = client or get_client(settings)
    live = settings.collection
    index_id = uuid.uuid4().hex[:12]
    build_name = f"{live}-build-{index_id}"
    metadata: dict[str, str | int | float | bool] = {
        "hnsw:space": "cosine",
        "embed_model": settings.embed_model,
        "dimension": dims.pop(),
        "index_id": index_id,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunks": len(chunks),
    }
    fresh = client.create_collection(name=build_name, metadata=metadata)
    try:
        for start in range(0, len(chunks), ADD_BATCH):
            part = slice(start, start + ADD_BATCH)
            fresh.add(
                ids=ids[part],
                documents=[c.text for c in chunks[part]],
                embeddings=vectors[part],
                metadatas=[c.metadata() for c in chunks[part]],
            )
        if fresh.count() != len(chunks):
            raise RuntimeError(f"stored {fresh.count()} chunks, expected {len(chunks)}")
        old_name = f"{live}-old-{index_id}"
        try:
            old = client.get_collection(live)
        except Exception:  # first build: nothing to replace
            old = None
        if old is not None:
            old.modify(name=old_name)
        fresh.modify(name=live)
        if old is not None:
            client.delete_collection(old_name)
    except Exception:
        try:
            client.delete_collection(build_name)
        except Exception:
            pass
        raise
    return len(chunks)
