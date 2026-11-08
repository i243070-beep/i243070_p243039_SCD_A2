"""Lazy connections to Chroma and Redis.

Nothing here touches the network at import or at startup. That matters: if the process connected to Chroma
while starting, a slow Chroma would crash the pod, the liveness probe would restart it, and one slow
dependency would become a restart storm (section 4.3). A connection is made on first use, and /readyz is the
place that reports a dependency as unreachable.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings


class Dependencies:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._chroma: Any = None
        self._redis: Any = None

    def chroma(self) -> Any:
        if self._chroma is None:
            import chromadb  # the thin client, from chromadb-client in requirements.txt
            from chromadb.config import Settings as ChromaSettings

            self._chroma = chromadb.HttpClient(
                host=self.settings.chroma_host, port=self.settings.chroma_port,
                settings=ChromaSettings(anonymized_telemetry=False))
        return self._chroma

    def redis(self) -> Any:
        if self._redis is None:
            import redis

            self._redis = redis.Redis(host=self.settings.redis_host, port=self.settings.redis_port,
                                      socket_connect_timeout=2, socket_timeout=2)
        return self._redis

    def reset_chroma(self) -> None:
        """Drop the cached client after a failure so the next call reconnects."""
        self._chroma = None
