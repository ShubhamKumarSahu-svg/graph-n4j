from typing import Any
from urllib.parse import quote

from graph_n4j.llm.http_client import HTTPClient


class GeminiClient(HTTPClient):
    key_env = "GEMINI_API_KEY"
    default_model = "gemini-2.5-flash"
    default_url = "https://generativelanguage.googleapis.com/v1beta"

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model_override: str | None = None,
    ) -> str:
        config: dict[str, Any] = dict(temperature=temperature, maxOutputTokens=max_tokens)
        if json_mode:
            config["responseMimeType"] = "application/json"
        payload: dict[str, Any] = dict(
            contents=[
                dict(
                    role="model" if m["role"] == "assistant" else "user",
                    parts=[{"text": m["content"]}],
                )
                for m in messages
                if m["role"] != "system"
            ],
            generationConfig=config,
        )
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        model = quote(model_override or self.model, safe="")
        data = self.post(
            f"/models/{model}:generateContent", payload, {"x-goog-api-key": self.api_key}
        )
        usage = data.get("usageMetadata", {})
        self.usage.add(usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0))
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
