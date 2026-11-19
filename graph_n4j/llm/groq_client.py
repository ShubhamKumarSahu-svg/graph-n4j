"""Send chat requests to Groq and record token usage across retrieval rounds."""

import logging
import os
import random
import time
from typing import Any, Optional

from groq import APIError, APITimeoutError, Groq, RateLimitError

from graph_n4j.llm.base import BaseLLMClient, TokenUsage

logger = logging.getLogger(__name__)

# Default model - configurable via GROQ_MODEL env var.
# Llama 3.3 70B Versatile is a strong code+reasoning model on Groq.
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class GroqClient(BaseLLMClient):
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
                "GROQ_API_KEY is missing. Set it to use the 'ask' command; "
                "indexing does not need a Groq key."
            )

        self.model = model or (os.getenv("GROQ_MODEL") or DEFAULT_MODEL)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

        self._client = Groq(api_key=self.api_key)
        self.usage = TokenUsage()

        logger.info("GroqClient initialized - model=%s", self.model)

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

        last_error: Exception | None = None
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
                    "Groq call #%d - model=%s, tokens=%s",
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
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                )
                time.sleep(delay)

            except APITimeoutError as e:
                last_error = e
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "API timeout (attempt %d/%d). Retrying in %.1fs...",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                )
                time.sleep(delay)

            except APIError as e:
                # Non-retryable API errors
                logger.error("Groq API error: %s", e)
                raise

        raise RuntimeError(f"Groq API failed after {self.max_retries + 1} attempts: {last_error}")

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter."""
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        jitter = random.uniform(0, delay * 0.5)
        return float(delay + jitter)
