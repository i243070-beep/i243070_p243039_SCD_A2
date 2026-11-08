"""Week-1 retriever: the same three passages for every question.

It lets you deploy and test the whole cluster before the RAG lecture.
Switch to RETRIEVER=chroma in the ConfigMap once your index exists.
"""

from __future__ import annotations

from ..schemas import Passage

_PASSAGES = [
    Passage(
        chunk_id="stub-001",
        text="This is a stub passage. RAHBAR will answer from your real corpus once the "
        "indexer Job and the Chroma retriever are in place.",
        source="stub-handbook.pdf",
        section="1.1 About the stub",
        page=1,
        score=0.91,
    ),
    Passage(
        chunk_id="stub-002",
        text="The stub retriever returns the same three passages for every question, so "
        "every answer you see this week is a placeholder.",
        source="stub-handbook.pdf",
        section="1.2 What the stub returns",
        page=1,
        score=0.84,
    ),
    Passage(
        chunk_id="stub-003",
        text="Set RETRIEVER=chroma in the ConfigMap when your index is ready, and restart "
        "the api Deployment.",
        source="stub-handbook.pdf",
        section="1.3 Switching to Chroma",
        page=2,
        score=0.77,
    ),
]


class StubRetriever:
    name = "stub"

    def retrieve(self, question: str, k: int) -> list[Passage]:
        return [p.model_copy() for p in _PASSAGES[:k]]
