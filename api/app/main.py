"""The API process. It reads the index; it never builds it (section 4.2).

Run locally with stubs:   make dev     (then open http://localhost:8000)
Run in the container:     uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .logjson import configure_logging, request_id_var
from .providers.llm import get_provider
from .retrieval import get_retriever
from .retrieval.chroma import ChromaRetriever
from .routes import ask, health, metrics
from .services.cache import SemanticCache
from .services.deps import Dependencies
from .services.readiness import check_readiness

log = logging.getLogger("rahbar.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    retriever = get_retriever(settings)
    app.state.retriever = retriever
    app.state.provider = get_provider(settings)
    # Connections are lazy: nothing below touches the network, so a slow Chroma cannot crash the pod
    # (and liveness never depends on it). /readyz is where an unreachable dependency is reported.
    deps = getattr(retriever, "deps", None) or Dependencies(settings)
    app.state.deps = deps
    app.state.cache = None
    if isinstance(retriever, ChromaRetriever):  # the cache needs the real embedder and the index id
        app.state.cache = SemanticCache(deps, retriever.embedder, settings.cache_threshold,
                                        lambda: retriever.index_info().index_id)
    # The embedding pin (section 4.4): compare the collection's embedding model with EMBED_MODEL and log exactly
    # what conflicts. Done in the background so startup never waits on Chroma; /readyz re-checks on every probe
    # and answers 503 on a mismatch, so a pod with the wrong model is never given traffic.
    threading.Thread(target=check_readiness, args=(settings, deps), daemon=True).start()
    # This process only reads the index. The indexer Job writes it.
    log.info(
        "api started",
        extra={"retriever": settings.retriever, "llm_provider": settings.llm_provider,
               "embed_model": settings.embed_model, "top_k": settings.top_k},
    )
    yield


app = FastAPI(title="RAHBAR API", lifespan=lifespan)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = request_id_var.set(rid)
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")   # route template, not the raw URL
        elapsed = time.perf_counter() - start
        metrics.REQUESTS.labels(path=path, status=str(status)).inc()
        metrics.LATENCY.labels(path=path).observe(elapsed)
        if path not in ("/healthz", "/readyz", "/metrics"):
            log.info("request", extra={"path": path, "status": status,
                                       "ms": round(elapsed * 1000, 1)})
        request_id_var.reset(token)


app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(ask.router)

# Development only: `make dev` serves the chat UI from this process, so you can try it
# without a cluster. On Kubernetes the ui Deployment serves it and this stays unset.
_ui_dir = os.environ.get("SERVE_UI_DIR")
if _ui_dir:
    app.mount("/", StaticFiles(directory=_ui_dir, html=True), name="ui")
