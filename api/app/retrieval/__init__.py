from __future__ import annotations

from ..config import Settings
from .base import Retriever


def get_retriever(settings: Settings) -> Retriever:
    if settings.retriever == "stub":
        from .stub import StubRetriever

        return StubRetriever()
    if settings.retriever == "chroma":
        from .chroma import ChromaRetriever

        return ChromaRetriever(settings)
    raise ValueError(f"unknown RETRIEVER {settings.retriever!r}; expected stub or chroma")
