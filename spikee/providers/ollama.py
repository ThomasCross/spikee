import os
from typing import Any

import requests
from any_llm import AnyLLM

from spikee.templates.provider import Provider
from spikee.utilities.enums import ModuleTag
from spikee.utilities.hinting import ModuleDescriptionHint
from spikee.utilities.llm_message import AIMessage, MessageHint, format_messages


class AnyLLMOllamaProvider(Provider):
    """AnyLLM provider for Ollama models"""

    BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

    stored_models: dict[str, str] | None = None

    @property
    def default_model(self) -> str:
        if self.stored_models is not None and len(self.stored_models) > 0:
            return next(iter(self.stored_models.keys()))

        else:
            return "none"

    @property
    def models(self) -> dict[str, str]:
        if self.stored_models is None:
            models = self.get_ollama_models()
            if "error" in models:
                self.stored_models = {models["error"]: models["error"]}
            else:
                self.stored_models = models

        return self.stored_models

    def get_ollama_models(self) -> dict[str, str]:
        """Programmatically gather the list of local models see: ollama list"""
        try:
            response = requests.get(f"{self.BASE_URL}/api/tags")
            data = response.json()
            return {model["model"]: model["model"] for model in data["models"]}

        except (KeyError, TypeError, ValueError, requests.RequestException):
            return {"error": "Unable to fetch models from Ollama API."}

    def setup(
        self,
        model: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

        timeout = kwargs.get("timeout", self.default_timeout)
        llm_kwargs = {"api_base": self.BASE_URL}
        if timeout is not None:
            llm_kwargs["timeout"] = timeout

        try:
            self.llm = AnyLLM.create("ollama", **llm_kwargs)
        except ImportError:
            raise ImportError(
                "[Import Error] Provider Module 'ollama' is missing required packages for Ollama. Please run `pip install spikee[ollama]` to install them."
            )

        options_kwargs: dict[str, Any] = {}
        if self.max_tokens is not None:
            options_kwargs["max_tokens"] = self.max_tokens

        if self.temperature is not None:
            options_kwargs["temperature"] = self.temperature

        self.options = options_kwargs

    def get_description(self) -> ModuleDescriptionHint:
        return [ModuleTag.LLM], "LLM Provider for Ollama models via any-llm."

    def _invoke(self, messages: MessageHint) -> AIMessage:
        """Invoke AnyLLM Ollama LLM with the provided messages."""

        formatted_messages = format_messages(messages)

        response = self.async_call(
            self.llm.acompletion,
            model=self.model,
            messages=formatted_messages,
            **self.options,
        )

        return AIMessage(
            content=response.choices[0].message.content, original_response=response
        )
