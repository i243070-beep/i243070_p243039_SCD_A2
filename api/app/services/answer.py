"""Turns a question into an AskResponse. This is where the query pipeline lives (section 3.2).

Order of the steps, each a small function that is unit-tested on its own:

  1. cache check            (skipped for follow-up questions)
  2. retrieve               (superseded documents filtered out unless an older version is asked for)
  3. relevance floor        (nothing relevant enough: abstain, WITHOUT calling the LLM)
  4. generate + validate    (parse and validate, retry once, then a safe canned fallback: never a 500)
  5. grounding              (the model said the corpus does not cover it: abstain)
  6. citation check         (a citation that matches no retrieved chunk is dropped; none left: abstain)
  7. store in the cache     (only a validated, grounded, cited, non-follow-up answer)
"""

from __future__ import annotations

import logging
import time

import httpx
from pydantic import ValidationError

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..providers.llm.hosted import ProviderError
from ..retrieval.base import Retriever
from ..routes import metrics
from ..schemas import Answer, AskResponse, Passage, RetrievedRef
from .cache import SemanticCache, is_cacheable, is_followup
from .grounding import check_citations, is_older_version_question

log = logging.getLogger("rahbar.answer")

ABSTAIN_TEXT = ("The documents I have do not cover this question, so I can't answer it from them. "
                "Please check with the university office.")
FALLBACK_TEXT = ("I could not produce a reliable answer right now. Please try again in a moment, "
                 "or rephrase the question.")

_GENERATION_ERRORS = (ValidationError, ValueError, ProviderError, httpx.HTTPError, TimeoutError)


def _canned(text: str) -> Answer:
    return Answer(reasoning="", answer=text, citations=[], answered_from_context=False, confidence="low")


def generate_validated(provider: LLMProvider, question: str, passages: list[Passage]) -> tuple[Answer | None, str]:
    """Call the provider; on a parse, validation or provider error retry once. Returns (answer, '') on success
    or (None, reason) when both attempts failed, so the caller can return the safe fallback."""
    reason = ""
    for attempt in (1, 2):
        try:
            return provider.generate(question, passages), ""
        except _GENERATION_ERRORS as exc:
            reason = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("generation failed", extra={"attempt": attempt, "error": reason})
    return None, reason


def _refs(passages: list[Passage]) -> list[RetrievedRef]:
    return [RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page, score=p.score)
            for p in passages]


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings,
    cache: SemanticCache | None = None,
) -> AskResponse:
    started = time.perf_counter()
    rid = request_id_var.get()
    followup = is_followup(question)

    # 1. cache
    if cache is not None and not followup:
        cached, similarity = cache.lookup(question)
        if cached is not None:
            metrics.record_cache("hit")
            log.info("answered", extra={"cached": True, "cache_similarity": round(similarity, 4),
                                        "answered_from_context": cached.answered_from_context,
                                        "ms": round((time.perf_counter() - started) * 1000, 1)})
            return cached.model_copy(update={"request_id": rid, "cached": True})
        metrics.record_cache("miss")
    else:
        metrics.record_cache("skipped")

    # 2. retrieve
    include_old = is_older_version_question(question)
    t0 = time.perf_counter()
    try:
        passages = retriever.retrieve(question, k=settings.top_k, include_superseded=include_old)
    except Exception as exc:  # Chroma or the embedder is down: a safe answer, not a 500
        log.exception("retrieval failed", extra={"error": type(exc).__name__})
        metrics.FALLBACKS.inc()
        return _response(rid, _canned(FALLBACK_TEXT), [], provider, abstained=False)
    metrics.RETRIEVAL_SECONDS.observe(time.perf_counter() - t0)

    best = max((p.score for p in passages), default=0.0)
    flags: dict[str, object] = {"fallback": False, "abstained": False, "citations_rejected": 0}

    # 3. relevance floor: honest abstention without spending an LLM call
    # (a passage that literally contains an exact token from the question is evidence even if its vector score is low)
    if not passages or (best < settings.relevance_floor and not any(p.exact_match for p in passages)):
        metrics.ABSTENTIONS.inc()
        flags["abstained"] = True
        return _finish(rid, _canned(ABSTAIN_TEXT), passages, provider, settings, question, started, best,
                       include_old, flags, cache=None, validated=True)

    # 4. generate and validate (one retry, then the safe fallback)
    t1 = time.perf_counter()
    answer, reason = generate_validated(provider, question, passages)
    metrics.GENERATION_SECONDS.observe(time.perf_counter() - t1)
    if answer is None:
        metrics.FALLBACKS.inc()
        flags["fallback"] = True
        return _finish(rid, _canned(FALLBACK_TEXT), passages, provider, settings, question, started, best,
                       include_old, flags, cache=None, validated=False)

    # 5. grounding: the model itself says the documents do not cover the question
    if not answer.answered_from_context:
        metrics.ABSTENTIONS.inc()
        flags["abstained"] = True
        text = answer.answer.strip() or ABSTAIN_TEXT
        return _finish(rid, _canned(text), passages, provider, settings, question, started, best,
                       include_old, flags, cache=None, validated=True)

    # 6. citation check: every citation must match a chunk that was actually retrieved
    valid, rejected = check_citations(answer, passages)
    if rejected:
        metrics.CITATIONS_REJECTED.inc(rejected)
        flags["citations_rejected"] = rejected
    if not valid:  # claims to be grounded but nothing it cites was retrieved: do not present it as grounded
        metrics.ABSTENTIONS.inc()
        flags["abstained"] = True
        return _finish(rid, _canned(ABSTAIN_TEXT), passages, provider, settings, question, started, best,
                       include_old, flags, cache=None, validated=True)
    answer = answer.model_copy(update={"citations": valid})
    return _finish(rid, answer, passages, provider, settings, question, started, best, include_old, flags,
                   cache=cache, validated=True)


def _response(rid: str, answer: Answer, passages: list[Passage], provider: LLMProvider, abstained: bool) -> AskResponse:
    return AskResponse(
        request_id=rid, answer=answer.answer, citations=answer.citations,
        answered_from_context=answer.answered_from_context, confidence=answer.confidence,
        retrieved=_refs(passages), provider=provider.name,
    )


def _finish(rid: str, answer: Answer, passages: list[Passage], provider: LLMProvider, settings: Settings,
            question: str, started: float, best: float, include_old: bool, flags: dict[str, object],
            cache: SemanticCache | None, validated: bool) -> AskResponse:
    response = _response(rid, answer, passages, provider, bool(flags["abstained"]))
    if cache is not None and is_cacheable(question, response, validated):
        cache.store(question, response)
    # one line per request: where the five of six failure stages are visible when an answer is wrong
    log.info("answered", extra={
        "retriever": "chroma" if passages else "none", "provider": provider.name, "top_k": settings.top_k,
        "chunk_ids": [p.chunk_id for p in passages], "scores": [round(p.score, 4) for p in passages],
        "best_score": round(best, 4), "relevance_floor": settings.relevance_floor,
        "include_superseded": include_old, "answered_from_context": response.answered_from_context,
        "abstained": flags["abstained"], "fallback": flags["fallback"],
        "citations_rejected": flags["citations_rejected"], "cached": False,
        "ms": round((time.perf_counter() - started) * 1000, 1),
    })
    return response
