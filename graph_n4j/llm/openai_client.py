from typing import Any

from graph_n4j.llm.http_client import HTTPClient


class OpenAIClient(HTTPClient):
    key_env = "OPENAI_API_KEY"
    default_model = "gpt-4o"
    default_url = "https://api.openai.com/v1"

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model_override: str | None = None,
    ) -> str:
        model = model_override or self.model
        payload: dict[str, Any] = dict(
            model=model, messages=messages, max_completion_tokens=max_tokens
        )
        if not model.startswith(("o1", "o3", "o4")):
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self.post("/chat/completions", payload, {"Authorization": "Bearer " + self.api_key})
        usage = data.get("usage", {})
        self.usage.add(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        return str(data["choices"][0]["message"].get("content") or "")
