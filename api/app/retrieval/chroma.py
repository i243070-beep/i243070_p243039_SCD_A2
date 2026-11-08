"""The real retriever. Yours to build (sections 3.2 and 4.4).

Connection details are already here; the query is not.
"""

from __future__ import annotations

from ..config import Settings
from ..schemas import Passage


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb  # the thin client, from chromadb-client in requirements.txt
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                          settings=ChromaSettings(anonymized_telemetry=False))

    def retrieve(self, question: str, k: int) -> list[Passage]:
        # STARTER-TODO(3.2): embed the question with settings.embed_model (the same model
        # the indexer used), query the collection for the top k, filter out superseded
        # documents, and map each hit to a Passage. Chroma returns cosine *distance*;
        # Passage.score expects similarity, so convert: similarity = 1 - distance.
        raise NotImplementedError("ChromaRetriever.retrieve: see STARTER-TODO(3.2)")
