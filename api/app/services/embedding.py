"""Embed a question with the SAME model that indexed the chunks (section 3.2, 4.4)."""

from __future__ import annotations

import threading

import httpx

from ..config import Settings

# nomic-embed-text is trained with task prefixes: documents "search_document: ", questions "search_query: ".
QUERY_PREFIX = "search_query: "
_MEMO_SIZE = 256


class QueryEmbedder:
    """Calls Ollama's /api/embed. The last results are remembered so the cache lookup and the retrieval of the
    same question share one embedding instead of paying for two."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.url = f"{settings.ollama_url.rstrip('/')}/api/embed"
        self.model = settings.embed_model
        self._client = client or httpx.Client(timeout=settings.embed_timeout)
        self._memo: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        with self._lock:
            hit = self._memo.get(text)
        if hit is not None:
            return hit
        last: Exception | None = None
        for _ in range(2):  # one retry: a request can be dropped while Ollama loads the model
            try:
                response = self._client.post(self.url, json={"model": self.model, "input": [QUERY_PREFIX + text]})
                response.raise_for_status()
                vector = [float(x) for x in response.json()["embeddings"][0]]
                break
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last = exc
        else:
            raise RuntimeError(f"could not embed the question with {self.model!r}: {last}")
        with self._lock:
            if len(self._memo) >= _MEMO_SIZE:
                self._memo.pop(next(iter(self._memo)))
            self._memo[text] = vector
        return vector
