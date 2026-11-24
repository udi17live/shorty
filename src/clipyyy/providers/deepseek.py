"""DeepSeek Direct API provider implementation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from clipyyy.providers.base import LLMAuthenticationError
from clipyyy.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class DeepSeekProvider(OpenAICompatibleProvider):
    """Direct DeepSeek API integration (OpenAI-compatible protocol)."""

    def __init__(
        self,
        api_key: str = "",
        model: str | None = None,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 300.0,
    ) -> None:
        if not api_key:
            raise LLMAuthenticationError(
                "No API key for DeepSeek. Add it in Settings or run "
                "`clipyyy config set deepseek_api_key <key>`."
            )
        effective_base_url = (base_url or DEFAULT_BASE_URL).strip()
        effective_model = (model or DEFAULT_MODEL).strip()
        super().__init__(
            name="DeepSeek",
            base_url=effective_base_url,
            api_key=api_key,
            model=effective_model,
            transport=transport,
            timeout=timeout,
        )

    def _build_response_format(self, schema: dict[str, Any], name: str) -> dict[str, Any] | None:
        """DeepSeek Chat Completions API supports {"type": "json_object"} rather than "json_schema"."""
        return {"type": "json_object"}

    def list_models(self) -> list[dict[str, Any]]:
        """Fetch available models from DeepSeek API, with sensible fallbacks."""
        try:
            response = self._client.get("/models")
            if response.status_code == 200:
                data = response.json().get("data", [])
                models = [
                    {"id": item["id"], "name": item.get("name", item["id"])}
                    for item in data
                    if "id" in item
                ]
                if models:
                    return sorted(models, key=lambda m: m["id"])
        except Exception as exc:
            logger.warning("Could not query DeepSeek models: %s", exc)

        # Fallback to standard known DeepSeek models if listing fails or returns empty
        return [
            {"id": "deepseek-flash", "name": "deepseek-flash (DeepSeek-V4.1-Flash)"},
            {"id": "deepseek-v4-pro", "name": "deepseek-v4-pro (DeepSeek-V4-Pro)"},
            {"id": "deepseek-chat", "name": "deepseek-chat (DeepSeek-V3)"},
            {"id": "deepseek-reasoner", "name": "deepseek-reasoner (DeepSeek-R1)"},
        ]

