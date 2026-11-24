"""Factory and registry for LLM providers."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from shortyy.config import get_setting
from shortyy.providers.base import LLMError, LLMProvider
from shortyy.providers.deepseek import DeepSeekProvider
from shortyy.providers.ollama import OllamaProvider
from shortyy.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


class LLMProviderFactory:
    """Registry and factory resolving LLM providers based on configuration."""

    _registry: dict[str, type[LLMProvider]] = {
        "deepseek": DeepSeekProvider,
        "openrouter": OpenRouterProvider,
        "ollama": OllamaProvider,
    }

    @classmethod
    def register(cls, name: str, provider_cls: type[LLMProvider]) -> None:
        """Register a new LLM provider driver."""
        cls._registry[name.lower().strip()] = provider_cls

    @classmethod
    def registered_providers(cls) -> list[str]:
        """Return list of registered provider identifiers."""
        return sorted(cls._registry.keys())

    @classmethod
    def create(
        cls,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 300.0,
        **kwargs: Any,
    ) -> LLMProvider:
        """Instantiate the configured or requested LLM provider."""
        provider_name = (provider or get_setting("llm_provider") or "openrouter").lower().strip()
        provider_cls = cls._registry.get(provider_name)

        if provider_cls is None:
            available = ", ".join(cls.registered_providers())
            raise LLMError(f"Unknown LLM provider '{provider_name}'. Available: {available}")

        if provider_name == "deepseek":
            key = api_key if api_key is not None else get_setting("deepseek_api_key")
            url = base_url or get_setting("deepseek_base_url") or None
            mod = model or get_setting("deepseek_model") or None
            return DeepSeekProvider(
                api_key=key,
                model=mod,
                base_url=url,
                transport=transport,
                timeout=timeout,
            )

        if provider_name == "openrouter":
            key = api_key if api_key is not None else get_setting("openrouter_api_key")
            url = base_url or get_setting("openrouter_base_url") or None
            # Fall back to legacy/global llm_model if openrouter_model is not set
            mod = model or get_setting("openrouter_model") or get_setting("llm_model") or None
            return OpenRouterProvider(
                api_key=key,
                model=mod,
                base_url=url,
                transport=transport,
                timeout=timeout,
            )

        if provider_name == "ollama":
            url = base_url or get_setting("ollama_base_url") or None
            mod = model or get_setting("ollama_model") or None
            return OllamaProvider(
                model=mod,
                base_url=url,
                api_key=api_key or "",
                transport=transport,
                timeout=timeout,
            )

        # For dynamically registered custom providers
        return provider_cls(  # type: ignore[call-arg]
            api_key=api_key or "",
            model=model or "",
            base_url=base_url or "",
            transport=transport,
            timeout=timeout,
            **kwargs,
        )

