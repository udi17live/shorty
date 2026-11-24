"""OpenAI-compatible LLM driver supporting standard chat completion protocols."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

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

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(r"(?:Bearer\s+|sk-)[a-zA-Z0-9_\-]{6,}", re.IGNORECASE)


class OpenAICompatibleProvider(LLMProvider):
    """Generic driver for providers adhering to the OpenAI Chat Completions API."""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str = "",
        model: str = "",
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport

        req_headers = dict(headers or {})
        if api_key:
            req_headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=req_headers,
            timeout=timeout,
            transport=transport,
        )

    def _build_response_format(self, schema: dict[str, Any], name: str) -> dict[str, Any] | None:
        """Construct the response_format parameter for structured output.

        Subclasses may override this to specify provider-specific formats
        (e.g., {"type": "json_object"} for DeepSeek).
        """
        return {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        }

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        fmt = self._build_response_format(schema, name)
        if fmt is not None:
            body["response_format"] = fmt

        response = self._post(body)
        err_detail = self._extract_error_detail(response).lower() if response.status_code >= 400 else ""
        has_fmt_err = "response_format" in response.text.lower() or "response_format" in err_detail
        if response.status_code == 400 and has_fmt_err:
            sanitized_body = self._sanitize_log_output(response.text)
            logger.warning(
                "%s (model=%s): HTTP 400 with response_format=%s: %s; falling back without response_format",
                self.name,
                self.model,
                fmt,
                sanitized_body,
            )
            body.pop("response_format", None)
            response = self._post(body)

        self._handle_response_errors(response)

        payload = response.json()
        if "error" in payload:
            self._raise_for_error_payload(payload["error"])

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            sanitized = self._sanitize_log_output(payload)
            raise LLMError(f"Unexpected response format from {self.name}: {sanitized}") from exc

        try:
            return parse_json(content)
        except LLMStructuredOutputError as exc:
            logger.warning(
                "%s (model=%s): failed to parse structured output: %s (content snippet: %s)",
                self.name,
                self.model,
                exc,
                self._sanitize_log_output(str(content)[:200]),
            )
            raise

    def _sanitize_log_output(self, value: Any, max_len: int = 500) -> str:
        text = str(value or "")
        masked = _SECRET_PATTERN.sub("[REDACTED_SECRET]", text)
        if len(masked) > max_len:
            return masked[:max_len] + "... [truncated]"
        return masked

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        delay = 2.0
        for attempt in range(4):
            try:
                response = self._client.post("/chat/completions", json=body)
            except httpx.TimeoutException as exc:
                if attempt == 3:
                    raise LLMTimeoutError(f"{self.name} request timed out after {self.timeout}s") from exc
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise LLMConnectionError(
                        f"Unable to connect to {self.name} at {self.base_url}: {exc}"
                    ) from exc
            else:
                if response.status_code not in {429, 500, 502, 503, 504} or attempt == 3:
                    return response
            time.sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")

    def _handle_response_errors(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return

        detail = self._extract_error_detail(response)
        status = response.status_code

        if status == 401 or status == 403:
            raise LLMAuthenticationError(
                f"{self.name} authentication failed ({status}): {detail or 'Invalid API key'}"
            )
        if status == 404:
            raise LLMModelNotFoundError(
                f"{self.name} resource or model '{self.model}' not found ({status}): {detail}"
            )
        if status == 429:
            raise LLMRateLimitError(f"{self.name} rate limit or quota exceeded ({status}): {detail}")

        raise LLMError(f"{self.name} error ({status}): {detail}")

    def _extract_error_detail(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, dict):
                    return str(err.get("message") or err)
                if err:
                    return str(err)
                return str(payload.get("detail") or payload.get("message") or "")
        except Exception:
            pass
        return response.text[:300]

    def _raise_for_error_payload(self, error: Any) -> None:
        msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        code = error.get("code") if isinstance(error, dict) else None
        if code in {401, "invalid_api_key"} or "auth" in msg.lower() or "api key" in msg.lower():
            raise LLMAuthenticationError(f"{self.name} authentication failed: {msg}")
        if code == 429 or "rate limit" in msg.lower() or "quota" in msg.lower():
            raise LLMRateLimitError(f"{self.name} rate limit exceeded: {msg}")
        raise LLMError(f"{self.name} error: {msg}")

    def test_connection(self) -> dict[str, Any]:
        """Verify connectivity, credentials, and model using a lightweight ping."""
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }
        try:
            ping_timeout = min(self.timeout, 15.0)
            response = self._client.post("/chat/completions", json=body, timeout=ping_timeout)
            self._handle_response_errors(response)
            payload = response.json()
            if "error" in payload:
                self._raise_for_error_payload(payload["error"])
        except LLMError:
            raise
        except Exception as exc:
            raise LLMConnectionError(f"Connection test failed for {self.name}: {exc}") from exc

        return {
            "ok": True,
            "provider": self.name.lower(),
            "model": self.model,
            "message": f"{self.name} connection successful",
        }

    def list_models(self) -> list[dict[str, Any]]:
        """Default model discovery using standard /models endpoint."""
        try:
            response = self._client.get("/models")
            self._handle_response_errors(response)
            data = response.json().get("data", [])
            models = []
            for item in data:
                model_id = item.get("id") or item.get("name")
                if model_id:
                    models.append({"id": model_id, "name": model_id})
            return sorted(models, key=lambda m: m["id"])
        except Exception as exc:
            logger.warning("Could not list models for %s: %s", self.name, exc)
            return [{"id": self.model, "name": self.model}] if self.model else []
