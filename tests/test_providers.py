import json

import httpx
import pytest

from graph_n4j.llm.anthropic_client import AnthropicClient
from graph_n4j.llm.gemini_client import GeminiClient
from graph_n4j.llm.ollama_client import OllamaClient
from graph_n4j.llm.openai_client import OpenAIClient


@pytest.mark.parametrize(
    "client_class,response",
    [
        (
            OpenAIClient,
            {
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            },
        ),
        (
            AnthropicClient,
            {
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
        ),
        (
            GeminiClient,
            {
                "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3},
            },
        ),
        (
            OllamaClient,
            {"message": {"content": '{"ok": true}'}, "prompt_eval_count": 2, "eval_count": 3},
        ),
    ],
)
def test_provider_contract(client_class, response):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response)

    client = client_class(api_key="test", transport=httpx.MockTransport(handler))
    assert client.chat_json(
        [{"role": "system", "content": "JSON"}, {"role": "user", "content": "hello"}]
    ) == {"ok": True}
    assert client.usage.total_tokens == 5
    assert requests[0].get("model", client.model) == client.model
    client.close()


def test_openai_reasoning_parameters():
    def handler(request):
        payload = json.loads(request.content)
        assert "temperature" not in payload
        assert payload["max_completion_tokens"] == 123
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = OpenAIClient(api_key="test", model="o3-mini", transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}], max_tokens=123) == "ok"
    client.close()
