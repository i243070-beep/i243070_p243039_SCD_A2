"""The real retriever (sections 3.2 and 4.4): embed the question, query Chroma, map hits to Passages.

The metadata filter `superseded = false` is what fixes failure mode E (a repealed clause quoted as current):
a prompt cannot do that, a filter can. It is dropped only when the user explicitly asks about an older version.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..schemas import Passage
from ..services.deps import Dependencies
from ..services.embedding import QueryEmbedder


@dataclass
class IndexInfo:
    index_id: str
    embed_model: str | None
    dimension: int | None
    count: int


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings, deps: Dependencies | None = None,
                 embedder: QueryEmbedder | None = None) -> None:
        self.settings = settings
        self.deps = deps or Dependencies(settings)
        self.embedder = embedder or QueryEmbedder(settings)
        self._info: tuple[float, IndexInfo] | None = None

    def _collection(self) -> Any:
        try:
            return self.deps.chroma().get_collection(self.settings.collection)
        except Exception:
            # the indexer swaps the collection in by rename; retry once, with a fresh connection
            self.deps.reset_chroma()
            time.sleep(0.3)
            return self.deps.chroma().get_collection(self.settings.collection)

    def index_info(self, max_age: float = 30.0) -> IndexInfo:
        """The current index's id and pin, cached for a short time. The semantic cache keys its entries by
        `index_id`, so a re-index (a new id) invalidates every cached answer without touching Redis."""
        now = time.monotonic()
        if self._info is not None and now - self._info[0] < max_age:
            return self._info[1]
        collection = self._collection()
        meta = collection.metadata or {}
        info = IndexInfo(index_id=str(meta.get("index_id", "unknown")), embed_model=meta.get("embed_model"),
                         dimension=meta.get("dimension"), count=int(collection.count()))
        self._info = (now, info)
        return info

    @staticmethod
    def _to_passages(result: dict[str, Any], exact: bool) -> list[Passage]:
        passages: list[Passage] = []
        for chunk_id, document, meta, distance in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0],
                strict=True):
            passages.append(Passage(
                chunk_id=chunk_id, text=document, source=str(meta["source"]), section=str(meta["section"]),
                page=int(meta["page"]) if meta.get("page") is not None else None,
                score=1.0 - float(distance),  # Chroma returns cosine distance; Passage.score is similarity
                exact_match=exact,
            ))
        return passages

    def retrieve(self, question: str, k: int, include_superseded: bool = False) -> list[Passage]:
        vector = self.embedder.embed(question)
        where = None if include_superseded else {"superseded": False}
        collection = self._collection()
        include = ["documents", "metadatas", "distances"]
        passages = self._to_passages(collection.query(
            query_embeddings=[vector], n_results=k, where=where, include=include), exact=False)
        # Hybrid retrieval: embeddings blur exact terms such as "clause 1.21", so also ask for chunks whose
        # text literally contains that token (ranked among themselves by vector distance), and put them first.
        rescued: list[Passage] = []
        for token in exact_tokens(question)[:2]:
            try:
                rescued.extend(self._to_passages(collection.query(
                    query_embeddings=[vector], n_results=2, where=where,
                    where_document={"$contains": token}, include=include), exact=True))
            except Exception:  # no chunk contains the token (or the filter is unsupported): keep the vector hits
                continue
        merged: dict[str, Passage] = {}
        for p in rescued + passages:
            merged.setdefault(p.chunk_id, p)
        return list(merged.values())[:k]


_EXACT = re.compile(r"\b\d{1,2}(?:\.\d{1,2}){1,3}\b|\b[A-Z]{2,5}\s?-?\d{3,4}\b")


def exact_tokens(question: str) -> list[str]:
    """Exact terms embeddings tend to blur: clause numbers (1.21, 5.4.1) and course codes (CS1002)."""
    seen: list[str] = []
    for match in _EXACT.findall(question):
        token = match.replace(" ", "")
        if token not in seen:
            seen.append(token)
    return seen
