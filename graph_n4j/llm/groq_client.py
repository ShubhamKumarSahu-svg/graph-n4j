"""
groq_client.py — Groq LLM wrapper with retry/backoff and token usage tracking.

Provides:
  - GroqClient: thin wrapper around the Groq Python SDK
  - Exponential backoff with jitter for rate-limit resilience
  - Running token-usage counter (the paper notes CodexGraph increases token
    consumption vs. baselines — this lets us measure it)
  - Structured JSON output mode support
"""

import os
import re
import json
import time
import random
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

from groq import Groq, RateLimitError, APIError, APITimeoutError

logger = logging.getLogger(__name__)

# Default model — configurable via GROQ_MODEL env var.
# Llama 3.3 70B Versatile is a strong code+reasoning model on Groq.
DEFAULT_MODEL = "llama-3.3-70b-versatile"


@dataclass
class TokenUsage:
    """Cumulative token usage tracker."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0

    def add(self, prompt: int, completion: int):
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.call_count += 1

    def summary(self) -> str:
        return (
            f"Calls: {self.call_count} | "
            f"Prompt: {self.prompt_tokens:,} | "
            f"Completion: {self.completion_tokens:,} | "
            f"Total: {self.total_tokens:,}"
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "call_count": self.call_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    def reset(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.call_count = 0


class GroqClient:
    """
    Groq LLM client with retry logic and token tracking.

    Usage:
        client = GroqClient()
        response = client.chat(
            messages=[{"role": "user", "content": "Hello!"}],
            temperature=0.2,
        )
        print(response)         # the text content
        print(client.usage)     # cumulative token stats
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Groq API key required. Set GROQ_API_KEY env var or pass api_key=."
            )

        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

        self._client = Groq(api_key=self.api_key)
        self.usage = TokenUsage()

        logger.info("GroqClient initialized — model=%s", self.model)

    # ── Core chat completion ──────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model_override: Optional[str] = None,
    ) -> str:
        """
        Send a chat completion request to Groq with automatic retry on rate limits.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
            temperature: Sampling temperature (0.0 for deterministic).
            max_tokens: Maximum tokens in the response.
            json_mode: If True, request JSON output format.
            model_override: Override the default model for this call.

        Returns:
            The assistant's response text.
        """
        model = model_override or self.model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)

                # Track token usage
                if response.usage:
                    self.usage.add(
                        prompt=response.usage.prompt_tokens or 0,
                        completion=response.usage.completion_tokens or 0,
                    )

                content = response.choices[0].message.content or ""
                logger.debug(
                    "Groq call #%d — model=%s, tokens=%s",
                    self.usage.call_count,
                    model,
                    f"{response.usage.total_tokens}" if response.usage else "?",
                )
                return content

            except RateLimitError as e:
                last_error = e
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d). Retrying in %.1fs...",
                    attempt + 1, self.max_retries + 1, delay,
                )
                time.sleep(delay)

            except APITimeoutError as e:
                last_error = e
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "API timeout (attempt %d/%d). Retrying in %.1fs...",
                    attempt + 1, self.max_retries + 1, delay,
                )
                time.sleep(delay)

            except APIError as e:
                # Non-retryable API errors
                logger.error("Groq API error: %s", e)
                raise

        raise RuntimeError(
            f"Groq API failed after {self.max_retries + 1} attempts: {last_error}"
        )

    # ── Convenience: JSON chat ────────────────────────────

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        model_override: Optional[str] = None,
    ) -> dict:
        """
        Chat with JSON output mode. Parses the response into a dict.
        Falls back to extracting JSON from the response text if parsing fails.
        """
        raw = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            model_override=model_override,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown fences
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise ValueError(f"Could not parse JSON from Groq response: {raw[:200]}")

    # ── Convenience: Cypher extraction ────────────────────

    def chat_cypher(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        model_override: Optional[str] = None,
    ) -> str:
        """
        Chat expecting a Cypher query response.
        Strips markdown fences defensively.
        """
        raw = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=False,
            model_override=model_override,
        )
        return self._strip_cypher_fences(raw)

    @staticmethod
    def _strip_cypher_fences(text: str) -> str:
        """Remove ```cypher ... ``` fences from LLM output."""
        text = text.strip()
        # Remove opening fence
        text = re.sub(r"^```(?:cypher|CYPHER)?\s*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)
        return text.strip()

    # ── Backoff calculation ───────────────────────────────

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter = random.uniform(0, delay * 0.5)
        return delay + jitter
