"""Prometheus metrics at /metrics (section 4.8).

Request count and latency, plus the production measurements: retrieval latency, generation latency, cache
lookups and the cache hit ratio, abstentions, fallbacks, rejected citations, and tokens in and out.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

router = APIRouter()

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
RETRIEVAL_SECONDS = Histogram(
    "rahbar_retrieval_seconds", "Time to embed the question and query Chroma",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5))
GENERATION_SECONDS = Histogram(
    "rahbar_generation_seconds", "Time spent in the LLM call, including the retry",
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60))
CACHE_LOOKUPS = Counter("rahbar_cache_lookups_total", "Semantic cache lookups", ["result"])  # hit|miss|skipped
CACHE_HIT_RATIO = Gauge("rahbar_cache_hit_ratio", "Cache hits divided by lookups that were attempted")
ABSTENTIONS = Counter("rahbar_abstentions_total", "Questions the corpus does not cover (answered_from_context false)")
FALLBACKS = Counter("rahbar_fallbacks_total", "Times the safe canned answer was returned after validation failed")
CITATIONS_REJECTED = Counter("rahbar_citations_rejected_total", "Citations dropped because no retrieved chunk matched")
TOKENS = Counter("rahbar_llm_tokens_total", "LLM tokens used", ["direction"])  # in|out

_hits = 0
_misses = 0


def record_cache(result: str) -> None:
    """Count a lookup and keep the hit ratio current. 'skipped' lookups are not part of the ratio."""
    global _hits, _misses
    CACHE_LOOKUPS.labels(result=result).inc()
    if result == "hit":
        _hits += 1
    elif result == "miss":
        _misses += 1
    if _hits + _misses:
        CACHE_HIT_RATIO.set(_hits / (_hits + _misses))


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
