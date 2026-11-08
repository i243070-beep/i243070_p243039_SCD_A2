"""Hosted free-tier provider: Google AI Studio through its OpenAI-compatible endpoint (ADR 0004).

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command line. It never appears in a file
that is committed, and never in a log line or an error message.

Enforce, then validate (section 3.4): the request asks for JSON mode (`response_format`), the system message
spells out the exact keys, and the reply is still parsed and validated with Pydantic by the caller, because
structure can be guaranteed but truth cannot.
"""

from __future__ import annotations

import json
import re

import httpx

from ...config import Settings
from ...routes import metrics
from ...schemas import Answer, Passage
from ...services.grounding import SYSTEM_INSTRUCTIONS, build_user_prompt


class ProviderError(RuntimeError):
    """The provider could not be reached or refused the request. The message never contains the key."""


def extract_json(content: str) -> str:
    """Models sometimes wrap JSON in a Markdown fence or add a sentence around it; take the outermost object."""
    text = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("the reply contains no JSON object")
    return text[start:end + 1]


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings   # hosted_base_url, llm_model, llm_api_key, temperature, llm_timeout
        self._client = client or httpx.Client(timeout=settings.llm_timeout)

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        if not self.settings.llm_api_key:
            raise ProviderError("LLM_API_KEY is not set; create the Secret with `make secret`")
        body = {
            "model": self.settings.llm_model,
            "temperature": self.settings.temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": build_user_prompt(question, passages)},
            ],
            "response_format": {"type": "json_object"},
        }
        url = f"{self.settings.hosted_base_url.rstrip('/')}/chat/completions"
        try:
            response = self._client.post(
                url, json=body, headers={"Authorization": f"Bearer {self.settings.llm_api_key}"})
        except httpx.TimeoutException as exc:
            raise ProviderError(f"the LLM call timed out after {self.settings.llm_timeout:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"the LLM call failed ({type(exc).__name__})") from exc
        if response.status_code != 200:
            # status code only: a response body could echo request details
            raise ProviderError(f"the LLM provider returned HTTP {response.status_code}")
        data = response.json()
        usage = data.get("usage") or {}
        metrics.TOKENS.labels(direction="in").inc(int(usage.get("prompt_tokens") or 0))
        metrics.TOKENS.labels(direction="out").inc(int(usage.get("completion_tokens") or 0))
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("the reply has no message content") from exc
        return Answer.model_validate(json.loads(extract_json(content)))
