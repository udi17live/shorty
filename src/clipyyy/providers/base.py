"""Base abstractions for LLM providers."""

from __future__ import annotations

import json
import re
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


def _scan_json_values(text: str) -> list[dict[str, Any] | list[Any]]:
    decoder = json.JSONDecoder()
    pos = 0
    length = len(text)
    values: list[dict[str, Any] | list[Any]] = []
    while pos < length:
        next_brace = text.find("{", pos)
        next_bracket = text.find("[", pos)
        if next_brace == -1 and next_bracket == -1:
            break
        if next_brace != -1 and (next_bracket == -1 or next_brace < next_bracket):
            candidate_pos = next_brace
        else:
            candidate_pos = next_bracket
        try:
            val, end_idx = decoder.raw_decode(text, candidate_pos)
            if isinstance(val, (dict, list)):
                values.append(val)
                pos = end_idx
                continue
            else:
                pos = candidate_pos + 1
        except json.JSONDecodeError:
            pos = candidate_pos + 1
    return values


def parse_json(content: Any) -> dict[str, Any]:
    """Extract and parse JSON object or array from LLM response text or content list.

    Correctly handles:
    - Pure JSON objects and JSON arrays
    - Surrounding whitespace
    - Markdown ```json code fences
    - Harmless surrounding commentary when unambiguous
    - Detects multiple JSON values and raises LLMStructuredOutputError
    """
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    text = str(content or "").strip()

    # Fast path: pure JSON object or array
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return {"clips": data}
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # If markdown code fence is present, attempt extraction from the code block(s)
    pattern = r"```(?:[a-zA-Z0-9_-]+)?\s*\n?(.*?)\n?```"
    fenced_blocks = [m.strip() for m in re.findall(pattern, text, re.DOTALL) if m.strip()]
    if fenced_blocks:
        fenced_values: list[dict[str, Any] | list[Any]] = []
        for block in fenced_blocks:
            fenced_values.extend(_scan_json_values(block))
        if len(fenced_values) > 1:
            raise LLMStructuredOutputError(
                f"Model returned multiple JSON values ({len(fenced_values)} values found in code blocks). "
                f"Expected a single JSON object."
            )
        if len(fenced_values) == 1:
            val = fenced_values[0]
            return {"clips": val} if isinstance(val, list) else val

    # Scan the full text
    values = _scan_json_values(text)
    if len(values) > 1:
        raise LLMStructuredOutputError(
            f"Model returned multiple JSON values ({len(values)} values found). "
            f"Expected a single JSON object."
        )
    if len(values) == 1:
        val = values[0]
        return {"clips": val} if isinstance(val, list) else val

    if "{" in text or "[" in text:
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMStructuredOutputError(f"Model returned invalid JSON: {exc}: {text[:200]}") from exc
        raise LLMStructuredOutputError(f"Model returned invalid JSON: {text[:200]}")
    raise LLMStructuredOutputError(f"Model did not return JSON: {text[:200]}")


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

