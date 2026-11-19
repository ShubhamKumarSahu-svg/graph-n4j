from graph_n4j.llm.base import BaseLLMClient


def create_client(provider: str, model: str | None = None) -> BaseLLMClient:
    # Load provider adapters when constructing a client so importing the package stays lightweight.
    from graph_n4j.llm.anthropic_client import AnthropicClient
    from graph_n4j.llm.gemini_client import GeminiClient
    from graph_n4j.llm.groq_client import GroqClient
    from graph_n4j.llm.ollama_client import OllamaClient
    from graph_n4j.llm.openai_client import OpenAIClient

    clients: dict[str, type[BaseLLMClient]] = dict(
        groq=GroqClient,
        openai=OpenAIClient,
        anthropic=AnthropicClient,
        gemini=GeminiClient,
        ollama=OllamaClient,
    )
    if provider not in clients:
        raise ValueError(f"Unknown LLM provider: {provider}")
    return clients[provider](model=model)
