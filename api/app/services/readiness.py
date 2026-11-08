"""Readiness (section 4.3) and the embedding pin (section 4.4).

/readyz answers "can this pod take traffic now?": Chroma reachable, the collection exists and is non-empty, the
embedding model recorded in the collection matches EMBED_MODEL, and Redis reachable. The first failing check is
named in the 503, so `kubectl describe` and the logs say exactly which dependency to fix. A pod that fails is
removed from the Service but not restarted: readiness protects users, liveness protects the pod.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from .deps import Dependencies

log = logging.getLogger("rahbar.readiness")


@dataclass
class Readiness:
    ok: bool
    failed: str | None = None
    detail: str | None = None
    checks: dict[str, str] = field(default_factory=dict)

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": "ready" if self.ok else "not ready", "checks": self.checks}
        if not self.ok:
            out["failed"] = self.failed
            out["detail"] = self.detail
        return out


def pin_conflict(settings: Settings, metadata: dict[str, Any] | None) -> str | None:
    """None when the collection was built with the model this api is configured for, else a message that
    names exactly what conflicts."""
    meta = metadata or {}
    built_with = meta.get("embed_model")
    if built_with is None:
        return (f"collection {settings.collection!r} has no embed_model in its metadata, "
                f"so its embedding model cannot be verified against EMBED_MODEL={settings.embed_model!r}")
    if built_with != settings.embed_model:
        return (f"embedding model mismatch: collection {settings.collection!r} was built with "
                f"{built_with!r} (dimension {meta.get('dimension')}) but this api is configured with "
                f"EMBED_MODEL={settings.embed_model!r}; vectors from different models are not comparable")
    return None


_last_logged: str | None = None


def _fail(name: str, detail: str, checks: dict[str, str]) -> Readiness:
    global _last_logged
    checks[name] = "fail"
    message = f"{name}: {detail}"
    if message != _last_logged:  # log a failure when it changes, not every 10 s probe
        log.error("not ready: %s", message, extra={"failed": name, "detail": detail})
        _last_logged = message
    return Readiness(False, name, detail, checks)


def check_readiness(settings: Settings, deps: Dependencies) -> Readiness:
    global _last_logged
    checks: dict[str, str] = {}
    try:
        deps.chroma().heartbeat()
        checks["chroma"] = "ok"
    except Exception as exc:
        deps.reset_chroma()
        return _fail("chroma", f"not reachable at {settings.chroma_host}:{settings.chroma_port} ({type(exc).__name__})", checks)
    try:
        collection = deps.chroma().get_collection(settings.collection)
        count = int(collection.count())
    except Exception as exc:
        return _fail("collection", f"collection {settings.collection!r} does not exist yet ({type(exc).__name__}); run the indexer Job", checks)
    if count == 0:
        return _fail("collection", f"collection {settings.collection!r} is empty; run the indexer Job", checks)
    checks["collection"] = f"ok ({count} chunks)"
    conflict = pin_conflict(settings, collection.metadata)
    if conflict:
        return _fail("embedding_pin", conflict, checks)
    checks["embedding_pin"] = f"ok ({settings.embed_model})"
    try:
        deps.redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        return _fail("redis", f"not reachable at {settings.redis_host}:{settings.redis_port} ({type(exc).__name__})", checks)
    if _last_logged is not None:
        log.info("ready again after: %s", _last_logged)
        _last_logged = None
    return Readiness(True, checks=checks)
