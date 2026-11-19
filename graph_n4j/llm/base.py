"""Common provider contract and structured-output conveniences."""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.call_count += 1

    def reset(self) -> None:
        self.prompt_tokens = self.completion_tokens = self.total_tokens = self.call_count = 0

    def to_dict(self) -> dict[str, int]:
        return vars(self).copy()

    def summary(self) -> str:
        return (
            f"Calls: {self.call_count} | Prompt: {self.prompt_tokens} | "
            f"Completion: {self.completion_tokens} | Total: {self.total_tokens}"
        )


@dataclass
class LLMResponse:
    content: str
    usage: TokenUsage


class BaseLLMClient(ABC):
    model: str
    usage: TokenUsage

    def __init__(self, model: str | None = None):
        self.model = model or ""
        self.usage = TokenUsage()

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model_override: str | None = None,
    ) -> str:
        pass

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        raw = self.chat(messages, temperature, max_tokens, True, model_override)
        # Some providers wrap otherwise valid JSON in a Markdown code block.
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object")
        return result

    def chat_cypher(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0,
        max_tokens: int = 2048,
        model_override: str | None = None,
    ) -> str:
        return self._strip_cypher_fences(
            self.chat(messages, temperature, max_tokens, False, model_override)
        )

    @staticmethod
    def _strip_cypher_fences(text: str) -> str:
        return re.sub(r"^```(?:cypher|CYPHER)?\s*|\s*```$", "", text.strip()).strip()
