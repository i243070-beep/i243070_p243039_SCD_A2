"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    # STARTER-TODO(4.3, 4.4): return 503, naming the failed dependency, unless Chroma is
    # reachable, the collection exists and is non-empty, Redis is reachable, and the
    # collection's embedding model matches EMBED_MODEL. Until then this always says yes,
    # which is exactly the lie section 4.2 warns about.
    return {"status": "ready", "checks": {}}
