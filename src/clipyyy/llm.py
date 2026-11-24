"""Model-agnostic LLM integration with provider/driver architecture.

Supports DeepSeek Direct API, OpenRouter, and Ollama out of the box, with an extensible
driver interface for future providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from clipyyy.providers.base import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMModelNotFoundError,
    LLMProvider,
    LLMRateLimitError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    parse_json,
)
from clipyyy.providers.deepseek import DeepSeekProvider
from clipyyy.providers.factory import LLMProviderFactory
from clipyyy.providers.ollama import OllamaProvider
from clipyyy.providers.openai_compatible import OpenAICompatibleProvider
from clipyyy.providers.openrouter import OpenRouterProvider


class LLM(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any], name: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Provider:
    """Legacy provider metadata record kept for backward compatibility."""

    name: str
    base_url: str
    key_setting: str
    headers: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_setting="openrouter_api_key",
        headers={"HTTP-Referer": "https://github.com/T3-Venture-Labs-Limited/clipyyy", "X-Title": "clipyyy"},
    ),
    "deepseek": Provider(
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        key_setting="deepseek_api_key",
    ),
    "ollama": Provider(
        name="Ollama",
        base_url="http://localhost:11434/v1",
        key_setting="",
    ),
}


class OpenAICompatibleLLM(OpenAICompatibleProvider):
    """Backward-compatible wrapper accepting a legacy Provider object."""

    def __init__(
        self,
        provider: Provider,
        api_key: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 300.0,
    ) -> None:
        if not api_key and provider.key_setting:
            raise LLMAuthenticationError(
                f"No API key for {provider.name}. Add it in Settings or run "
                f"`clipyyy config set {provider.key_setting} <key>`."
            )
        self.provider = provider
        super().__init__(
            name=provider.name,
            base_url=provider.base_url,
            api_key=api_key,
            model=model,
            headers=provider.headers,
            transport=transport,
            timeout=timeout,
        )


def get_llm(model: str | None = None, provider: str | None = None) -> LLMProvider:
    """Factory helper returning an instantiated LLMProvider driver."""
    return LLMProviderFactory.create(provider=provider, model=model)


def list_models(provider: str | None = None) -> list[dict[str, Any]]:
    """List models available for the active (or requested) provider."""
    p = LLMProviderFactory.create(provider=provider)
    return p.list_models()


def test_connection(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Test connectivity, credentials, and model for the active or given provider."""
    p = LLMProviderFactory.create(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )
    return p.test_connection()


__all__ = [
    "PROVIDERS",
    "DeepSeekProvider",
    "LLM",
    "LLMAuthenticationError",
    "LLMConnectionError",
    "LLMError",
    "LLMModelNotFoundError",
    "LLMProvider",
    "LLMProviderFactory",
    "LLMRateLimitError",
    "LLMStructuredOutputError",
    "LLMTimeoutError",
    "OllamaProvider",
    "OpenAICompatibleLLM",
    "OpenAICompatibleProvider",
    "OpenRouterProvider",
    "Provider",
    "get_llm",
    "list_models",
    "parse_json",
    "test_connection",
]
