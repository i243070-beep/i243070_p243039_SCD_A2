"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.readiness import check_readiness

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    """Can this pod take traffic now? 200 only if Chroma is reachable, the collection exists and is
    non-empty, the collection's embedding model matches EMBED_MODEL, and Redis is reachable. Otherwise 503 naming
    the dependency that failed; the pod is withheld from the Service but not restarted."""
    result = check_readiness(request.app.state.settings, request.app.state.deps)
    return JSONResponse(status_code=200 if result.ok else 503, content=result.body())
