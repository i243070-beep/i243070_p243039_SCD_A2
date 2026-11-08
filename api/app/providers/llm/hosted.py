"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter). Yours to build.

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file you commit, and never in a log line.
"""

from __future__ import annotations

from ...config import Settings
from ...schemas import Answer, Passage


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # hosted_base_url, llm_model, llm_api_key, temperature

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        # STARTER-TODO(3.4): same contract as the Ollama provider, over the hosted API.
        # Many free tiers are OpenAI-compatible: POST {hosted_base_url}/chat/completions.
        raise NotImplementedError("HostedProvider.generate: see STARTER-TODO(3.4)")
