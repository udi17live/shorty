"""Base abstractions for LLM providers."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    """Base exception for all LLM errors."""
    pass


class LLMAuthenticationError(LLMError):
    """Raised when authentication fails (invalid or missing API key)."""
    pass


class LLMModelNotFoundError(LLMError):
    """Raised when the requested model does not exist or is inaccessible."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when provider rate limits or credit quotas are hit."""
    pass


class LLMConnectionError(LLMError):
    """Raised when network is down or the provider service is unreachable."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an LLM request times out."""
    pass


class LLMStructuredOutputError(LLMError):
    """Raised when LLM response cannot be parsed as valid JSON."""
    pass


def parse_json(content: Any) -> dict[str, Any]:
    """Extract and parse JSON object from LLM response text or content list."""
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMStructuredOutputError(f"Model did not return JSON: {text[:200]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMStructuredOutputError(f"Model returned invalid JSON: {exc}: {text[:200]}") from exc


class LLMProvider(ABC):
    """Abstract interface that every LLM provider driver must implement.

    The clipping pipeline and the rest of Clipyyy depend solely on this interface,
    never on provider-specific logic.
    """

    name: str
    model: str
    base_url: str

    @abstractmethod
    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
    ) -> dict[str, Any]:
        """Request a structured completion adhering to the provided JSON schema."""
        ...

    @abstractmethod
    def list_models(self) -> list[dict[str, Any]]:
        """List available models for this provider."""
        ...

    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        """Perform a minimal test to verify credentials, base URL, and model availability.

        Returns a dictionary with status, e.g.:
            {"ok": True, "provider": self.name, "model": self.model, "message": "..."}
        or raises an LLMError on failure.
        """
        ...

