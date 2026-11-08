"""Semantic cache in Redis (section 3.3, ADR 0003).

A hit is a cosine similarity at or above CACHE_THRESHOLD (a ConfigMap value chosen with data, see
docs/PIPELINE.md). Every key is prefixed with the `index_id` that the indexer writes into the Chroma collection
metadata, so a re-index changes the prefix and the old answers are simply never matched (and age out): the cache
is invalidated on re-index without the indexer ever talking to Redis.

Never cached (see `is_cacheable`): follow-up questions, abstentions and out-of-scope answers, fallbacks, and
anything that failed validation. A cached mistake is served to everyone.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable

import numpy as np

from ..schemas import AskResponse
from .deps import Dependencies
from .embedding import QueryEmbedder

log = logging.getLogger("rahbar.cache")

_FOLLOWUP = re.compile(
    r"^\s*(and|also|but|so|then|ok|okay|what about|how about|why|what if|and what about)\b|"
    r"^\s*(it|that|this|they|those|these)\b", re.IGNORECASE)


def is_followup(question: str) -> bool:
    """A question that only makes sense after a previous one ("and what about MS?"). Never cached, never served
    from the cache: the same words mean something else in another conversation."""
    return bool(_FOLLOWUP.search(question))


def is_cacheable(question: str, response: AskResponse, validated: bool) -> bool:
    return (validated and response.answered_from_context and bool(response.citations)
            and not is_followup(question))


class SemanticCache:
    def __init__(self, deps: Dependencies, embedder: QueryEmbedder, threshold: float,
                 index_id: Callable[[], str], ttl_seconds: int = 86400) -> None:
        self.deps, self.embedder, self.threshold = deps, embedder, threshold
        self.index_id, self.ttl = index_id, ttl_seconds

    def _prefix(self) -> str:
        return f"rahbar:cache:{self.index_id()}"

    def lookup(self, question: str) -> tuple[AskResponse | None, float]:
        """(cached response or None, best similarity seen). Never raises: a cache problem is a miss."""
        try:
            r = self.deps.redis()
            keys = list(r.smembers(f"{self._prefix()}:keys"))
            if not keys:
                return None, 0.0
            vector = np.array(self.embedder.embed(question), dtype=float)
            entries = r.mget(keys)
            best, best_sim = None, 0.0
            for key, raw in zip(keys, entries, strict=True):
                if raw is None:  # expired: remove it from the index set
                    r.srem(f"{self._prefix()}:keys", key)
                    continue
                entry = json.loads(raw)
                other = np.array(entry["vec"], dtype=float)
                sim = float(vector @ other / ((np.linalg.norm(vector) * np.linalg.norm(other)) or 1.0))
                if sim > best_sim:
                    best, best_sim = entry, sim
            if best is not None and best_sim >= self.threshold:
                return AskResponse.model_validate(best["response"]), best_sim
            return None, best_sim
        except Exception as exc:
            log.warning("cache lookup failed, treating it as a miss", extra={"error": type(exc).__name__})
            return None, 0.0

    def store(self, question: str, response: AskResponse) -> None:
        try:
            r = self.deps.redis()
            vector = self.embedder.embed(question)
            key = f"{self._prefix()}:e:{hashlib.sha1(question.encode()).hexdigest()[:16]}"
            payload = json.dumps({"q": question, "vec": vector, "response": response.model_dump()})
            r.set(key, payload, ex=self.ttl)
            r.sadd(f"{self._prefix()}:keys", key)
            r.expire(f"{self._prefix()}:keys", self.ttl)
        except Exception as exc:
            log.warning("cache store failed", extra={"error": type(exc).__name__})
