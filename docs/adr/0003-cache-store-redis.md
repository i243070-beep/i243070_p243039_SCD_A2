# ADR 0003: The semantic cache lives in Redis

## Status
Accepted · 2026-11-08

## Context
Many questions are asked twice with different words ("minimum CGPA to avoid warning" and "what CGPA keeps me off
academic warning"). A semantic cache answers the second one without retrieval and generation, which saves a call to
the hosted LLM (free tier, rate limited) and a few seconds. A cached mistake, however, is served to everyone, and a
cache that outlives a re-index serves answers from an index that no longer exists. The cache needs a store; the
assignment allows Redis or a second Chroma collection.

## Decision
Redis, as a Deployment with a PVC (`cache-data`, so entries survive a restart), a ClusterIP Service, reachable from the
api only (NetworkPolicy), with a 64 MB memory cap and `allkeys-lru` eviction.

* **A hit** is a cosine similarity at or above `CACHE_THRESHOLD` from the ConfigMap. The threshold is chosen with data:
  the lowest value with zero false hits on our test questions, with the values tried and the false hit that ruled one out
  recorded in `docs/PIPELINE.md`.
* **Never cached:** follow-up questions, abstentions, out-of-scope answers, and anything that failed validation.
* **Invalidation on re-index:** every cache key is prefixed with the `index_id` that the indexer writes into the Chroma
  collection metadata, and the API reads it. A new index has a new `index_id`, so old entries are simply never matched
  and age out under LRU. The indexer never has to reach Redis, which keeps the NetworkPolicy strict (Redis is reachable
  from the api only).

## Options considered
* **A second Chroma collection.** One fewer pod, and the similarity search comes for free. But it mixes cache entries
  with corpus data in one store (a bug could serve a cached answer as a source), offers no expiry or eviction, and would
  make the API write to Chroma, which breaks the rule that only the indexer writes.
* **Redis** (chosen): purpose-built for expiry and eviction, easy to namespace by `index_id`, and keeps Chroma read-only
  for the API.
* **An in-process dictionary in each API pod.** Three replicas would each have their own cache and lose it on restart.

## Consequences
* One more pod and PVC, and `/readyz` also checks that Redis is reachable.
* The similarity comparison is done in the API over a small number of cached questions; that is fine at this scale and
  would need a vector-capable cache (Redis Stack) if the cache grew into the thousands.
* Watch for: a threshold that is too low turns a near-miss into a wrong cached answer for everyone; this is why the
  threshold is measured and why abstentions are never cached.
