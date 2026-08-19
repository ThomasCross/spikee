import os

from spikee.providers.custom import AnyLLMCustomProvider


class AnyLLMOpenRouterProvider(AnyLLMCustomProvider):
    """AnyLLM provider for OpenRouter models (via Custom provider with OpenAI compatibility)"""

    @property
    def models(self) -> dict[str, str]:
        return {
            "google/gemini-2.5-flash": "google/gemini-2.5-flash",
            "anthropic/claude-3.5-haiku": "anthropic/claude-3.5-haiku",
            "meta-llama/llama-3.1-8b-instruct": "meta-llama/llama-3.1-8b-instruct",
            "openai/gpt-4o-mini": "openai/gpt-4o-mini",
        }

    @property
    def name(self) -> str:
        return "OpenRouter"

    @property
    def base_url(self) -> str:
        return "https://openrouter.ai/api/v1"

    @property
    def api_key(self) -> str | None:
        return os.getenv("OPENROUTER_API_KEY", None)
