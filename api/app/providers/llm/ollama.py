"""Ollama provider: ollama-host or ollama-incluster (section 3.5). Yours to build."""

from __future__ import annotations

from ...config import Settings
from ...schemas import Answer, Passage


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # ollama_url, llm_model, temperature

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        # STARTER-TODO(3.4): build the augmented prompt (instructions, numbered evidence,
        # then the question), call POST {ollama_url}/api/chat with the Answer schema as
        # the output format, and turn the reply into an Answer. Section 3.4 lists what
        # a production call needs around it; read it before you write this.
        raise NotImplementedError("OllamaProvider.generate: see STARTER-TODO(3.4)")
