"""Shared synchronous HTTP lifecycle with bounded transient-error retries."""

import os
import time
from typing import Any

import httpx

from graph_n4j.llm.base import BaseLLMClient, TokenUsage


class HTTPClient(BaseLLMClient):
    key_env = ""
    default_model = ""
    default_url = ""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key or (os.getenv(self.key_env) or "")
        self.model = model or (
            os.getenv(self.key_env.replace("API_KEY", "MODEL")) or self.default_model
        )
        self.base_url = (base_url or self.default_url).rstrip("/")
        self.usage = TokenUsage()
        self.http = httpx.Client(timeout=120, transport=transport)

    def post(
        self, path: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        if self.key_env and not self.api_key:
            raise ValueError(
                f"{self.key_env} is missing. Set it to use the 'ask' command; "
                "indexing does not need an LLM key."
            )
        # Back off on rate limits and temporary server errors. Surface other failures immediately.
        for attempt in range(3):
            response = self.http.post(self.base_url + path, json=payload, headers=headers)
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Expected an object response")
                return data
            time.sleep(2**attempt)
        raise RuntimeError("Request retries exhausted")

    def close(self) -> None:
        self.http.close()
