import os
from typing import Any

from graph_n4j.llm.http_client import HTTPClient


class OllamaClient(HTTPClient):
    default_model = "qwen2.5-coder"
    default_url = "http://localhost:11434"

    def __init__(self, **kwargs):
        kwargs.setdefault("base_url", os.getenv("OLLAMA_HOST", self.default_url))
        kwargs["model"] = kwargs.get("model") or os.getenv("OLLAMA_MODEL", self.default_model)
        super().__init__(**kwargs)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model_override: str | None = None,
    ) -> str:
        # Request a single response so token counts and the reply arrive together.
        payload: dict[str, Any] = dict(
            model=model_override or self.model,
            messages=messages,
            stream=False,
            options=dict(temperature=temperature, num_predict=max_tokens),
        )
        if json_mode:
            payload["format"] = "json"
        data = self.post("/api/chat", payload)
        self.usage.add(data.get("prompt_eval_count", 0), data.get("eval_count", 0))
        return str(data["message"]["content"])
