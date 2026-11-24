"""Ollama local model provider implementation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from shortyy.providers.base import LLMConnectionError, LLMModelNotFoundError
from shortyy.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


class OllamaProvider(OpenAICompatibleProvider):
    """Local model provider running Ollama."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str = "",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 300.0,
    ) -> None:
        raw_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self.raw_base_url = raw_url
        # Ollama's OpenAI compatibility endpoint lives under /v1
        v1_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
        effective_model = (model or DEFAULT_MODEL).strip()

        super().__init__(
            name="Ollama",
            base_url=v1_url,
            api_key=api_key or "ollama",  # Ollama OpenAI endpoint accepts dummy key
            model=effective_model,
            transport=transport,
            timeout=timeout,
        )

    def list_models(self) -> list[dict[str, Any]]:
        """List locally available models by querying Ollama's /api/tags or /v1/models."""
        # First try Ollama's native /api/tags endpoint
        try:
            native_client = httpx.Client(
                base_url=self.raw_base_url,
                timeout=15.0,
                transport=self.transport,
            )
            response = native_client.get("/api/tags")
            if response.status_code == 200:
                tags = response.json().get("models", [])
                models = []
                for item in tags:
                    name = item.get("name") or item.get("model")
                    if name:
                        models.append({"id": name, "name": name})
                if models:
                    return sorted(models, key=lambda m: m["id"])
        except Exception as exc:
            logger.debug("Failed querying Ollama /api/tags: %s", exc)

        # Fall back to OpenAI /v1/models
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
            logger.warning("Could not list Ollama models: %s", exc)

        return [{"id": self.model, "name": self.model}] if self.model else []

    def test_connection(self) -> dict[str, Any]:
        """Verify that Ollama server is running and the model is reachable."""
        try:
            native_client = httpx.Client(
                base_url=self.raw_base_url,
                timeout=10.0,
                transport=self.transport,
            )
            resp = native_client.get("/api/tags")
        except httpx.TransportError as exc:
            raise LLMConnectionError(
                f"Ollama connection failed: Cannot reach Ollama at {self.raw_base_url}. "
                "Ensure Ollama is running (`ollama serve`)."
            ) from exc
        except Exception as exc:
            raise LLMConnectionError(f"Ollama connection error: {exc}") from exc

        if resp.status_code >= 400:
            raise LLMConnectionError(
                f"Ollama returned HTTP {resp.status_code} at {self.raw_base_url}"
            )

        installed_models = [
            m.get("name", "").split(":")[0]
            for m in resp.json().get("models", [])
            if isinstance(m, dict)
        ]
        exact_models = [
            m.get("name", "")
            for m in resp.json().get("models", [])
            if isinstance(m, dict)
        ]

        # If we have model list and our requested model is not found, note it
        model_base = self.model.split(":")[0]
        if exact_models and (self.model not in exact_models and model_base not in installed_models):
            raise LLMModelNotFoundError(
                f"Ollama is running, but model '{self.model}' was not found. "
                f"Run `ollama pull {self.model}`. Installed: {', '.join(exact_models) or 'none'}"
            )

        return {
            "ok": True,
            "provider": "ollama",
            "model": self.model,
            "message": f"Ollama connection successful at {self.raw_base_url}",
        }
