"""Ollama provider: ollama-host or ollama-incluster (section 3.5).

Same contract as the hosted provider. The strongest enforcement Ollama offers is used: `format` is set to the JSON
schema of `Answer`, so the model is constrained to that shape; the caller still validates with Pydantic.
"""

from __future__ import annotations

import json

import httpx

from ...config import Settings
from ...routes import metrics
from ...schemas import Answer, Passage
from ...services.grounding import SYSTEM_INSTRUCTIONS, build_user_prompt
from .hosted import ProviderError, extract_json


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings   # ollama_url, llm_model, temperature, llm_timeout
        self._client = client or httpx.Client(timeout=settings.llm_timeout)

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        body = {
            "model": self.settings.llm_model,
            "stream": False,
            "format": Answer.model_json_schema(),   # constrained decoding to the Answer schema
            "options": {"temperature": self.settings.temperature},
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": build_user_prompt(question, passages)},
            ],
        }
        try:
            response = self._client.post(f"{self.settings.ollama_url.rstrip('/')}/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"the Ollama call timed out after {self.settings.llm_timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"the Ollama call failed ({type(exc).__name__})") from exc
        if response.status_code != 200:
            raise ProviderError(f"Ollama returned HTTP {response.status_code}")
        data = response.json()
        metrics.TOKENS.labels(direction="in").inc(int(data.get("prompt_eval_count") or 0))
        metrics.TOKENS.labels(direction="out").inc(int(data.get("eval_count") or 0))
        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ValueError("the reply has no message content") from exc
        return Answer.model_validate(json.loads(extract_json(content)))
