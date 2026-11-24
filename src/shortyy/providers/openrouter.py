"""OpenRouter provider implementation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from shortyy.providers.base import LLMAuthenticationError
from shortyy.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-3.8-flash"
HEADERS = {
    "HTTP-Referer": "https://github.com/T3-Venture-Labs-Limited/clipyyy",
    "X-Title": "Shortyy",
}


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter provider supporting hosted open and commercial models."""

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
                "No API key for OpenRouter. Add it in Settings or run "
                "`shortyy config set openrouter_api_key <key>`."
            )
        effective_base_url = (base_url or DEFAULT_BASE_URL).strip()
        effective_model = (model or DEFAULT_MODEL).strip()
        super().__init__(
            name="OpenRouter",
            base_url=effective_base_url,
            api_key=api_key,
            model=effective_model,
            headers=HEADERS,
            transport=transport,
            timeout=timeout,
        )

    def list_models(self) -> list[dict[str, Any]]:
        """Fetch models supporting structured outputs and return with pricing per million."""
        try:
            response = self._client.get("/models")
            self._handle_response_errors(response)
            models = []
            for item in response.json().get("data", []):
                params = item.get("supported_parameters") or []
                if item["id"].endswith(":batch"):
                    continue
                if params and "structured_outputs" not in params and "response_format" not in params:
                    continue
                pricing = item.get("pricing") or {}
                models.append(
                    {
                        "id": item["id"],
                        "name": item.get("name", item["id"]),
                        "context_length": item.get("context_length"),
                        "prompt_price_per_million": _per_million(pricing.get("prompt")),
                        "completion_price_per_million": _per_million(pricing.get("completion")),
                    }
                )
            return sorted(models, key=lambda m: m["id"])
        except Exception as exc:
            logger.warning("Could not list OpenRouter models: %s", exc)
            return [{"id": self.model, "name": self.model}] if self.model else []


def _per_million(value: Any) -> float | None:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None

