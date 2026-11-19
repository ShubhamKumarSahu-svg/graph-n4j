from graph_n4j.llm.http_client import HTTPClient


class AnthropicClient(HTTPClient):
    key_env = "ANTHROPIC_API_KEY"
    default_model = "claude-3-7-sonnet-latest"
    default_url = "https://api.anthropic.com/v1"

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model_override: str | None = None,
    ) -> str:
        # The Messages API takes system instructions outside the conversation history.
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        if json_mode:
            system += "\nReturn only a valid JSON object."
        data = self.post(
            "/messages",
            dict(
                model=model_override or self.model,
                system=system,
                messages=[m for m in messages if m["role"] != "system"],
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
        )
        usage = data.get("usage", {})
        self.usage.add(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        return "".join(
            block.get("text", "") for block in data["content"] if block["type"] == "text"
        )
