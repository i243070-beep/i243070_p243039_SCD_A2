"""The LLM provider interface (section 3.5). Swapping providers is one file."""

from __future__ import annotations

from typing import Protocol

from ...schemas import Answer, Passage


class LLMProvider(Protocol):
    name: str

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        """Answer the question from the passages, as an `Answer`."""
        ...
