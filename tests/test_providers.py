"""Comprehensive tests for LLM providers, factory, configuration, and integration."""

import json
from typing import Any

import httpx
import pytest

from clipyyy import db
from clipyyy.config import get_setting
from clipyyy.llm import (
    DeepSeekProvider,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMModelNotFoundError,
    LLMProvider,
    LLMProviderFactory,
    LLMRateLimitError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    OllamaProvider,
    OpenRouterProvider,
    get_llm,
)
from clipyyy.llm import (
    test_connection as do_test_connection,
)
from clipyyy.selection import select_clips


def json_reply(content: Any, status: int = 200) -> httpx.Response:
    if isinstance(content, str):
        payload = {"choices": [{"message": {"content": content}}]}
    else:
        payload = content
    return httpx.Response(status, json=payload)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)


# ── Factory & Registry Tests ──────────────────────────────────────────────────


def test_factory_creates_correct_provider():
    # OpenRouter
    p_or = LLMProviderFactory.create(provider="openrouter", api_key="sk-or-test", model="m1")
    assert isinstance(p_or, OpenRouterProvider)
    assert p_or.name == "OpenRouter"
    assert p_or.model == "m1"
    assert p_or.base_url == "https://openrouter.ai/api/v1"

    # DeepSeek
    p_ds = LLMProviderFactory.create(
        provider="deepseek", api_key="sk-ds-test", model="deepseek-chat"
    )
    assert isinstance(p_ds, DeepSeekProvider)
    assert p_ds.name == "DeepSeek"
    assert p_ds.model == "deepseek-chat"
    assert p_ds.base_url == "https://api.deepseek.com"

    # Ollama
    p_ol = LLMProviderFactory.create(provider="ollama", model="llama3.2")
    assert isinstance(p_ol, OllamaProvider)
    assert p_ol.name == "Ollama"
    assert p_ol.model == "llama3.2"
    assert p_ol.base_url == "http://localhost:11434/v1"


def test_factory_rejects_unknown_provider():
    with pytest.raises(LLMError, match="Unknown LLM provider 'anthropic'"):
        LLMProviderFactory.create(provider="anthropic")


def test_factory_extensibility_custom_provider():
    class CustomProvider(LLMProvider):
        name = "Custom"
        model = "custom-v1"
        base_url = "https://custom.ai"

        def __init__(self, **kwargs):
            self.model = kwargs.get("model") or "custom-v1"

        def complete_json(self, system: str, user: str, schema: dict, name: str) -> dict:
            return {"clips": []}

        def list_models(self) -> list[dict]:
            return [{"id": "custom-v1", "name": "custom-v1"}]

        def test_connection(self) -> dict:
            return {"ok": True, "provider": "custom", "model": self.model, "message": "Custom ok"}

    LLMProviderFactory.register("custom", CustomProvider)
    assert "custom" in LLMProviderFactory.registered_providers()

    created = LLMProviderFactory.create(provider="custom")
    assert isinstance(created, CustomProvider)
    assert created.complete_json("s", "u", {}, "n") == {"clips": []}


# ── Configuration & Backward Compatibility Tests ──────────────────────────────


def test_configuration_defaults_and_env(monkeypatch):
    # Backward compatibility: default is openrouter
    db.set_setting("llm_provider", None)
    monkeypatch.delenv("CLIPYYY_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert get_setting("llm_provider") == "openrouter"

    # LLM_PROVIDER env works
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    assert get_setting("llm_provider") == "deepseek"

    # Database setting takes priority over env
    db.set_setting("llm_provider", "ollama")
    assert get_setting("llm_provider") == "ollama"

    # Empty env var should fall back to default or fallback env
    db.set_setting("llm_provider", None)
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("CLIPYYY_LLM_PROVIDER", "ollama")
    assert get_setting("llm_provider") == "ollama"

    monkeypatch.setenv("CLIPYYY_LLM_PROVIDER", "")
    assert get_setting("llm_provider") == "openrouter"

    # DeepSeek settings
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-env")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://proxy.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    assert get_setting("deepseek_api_key") == "sk-ds-env"
    assert get_setting("deepseek_base_url") == "https://proxy.deepseek.com"
    assert get_setting("deepseek_model") == "deepseek-reasoner"

    # DeepSeek empty env falls back to default
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "")
    assert get_setting("deepseek_base_url") == "https://api.deepseek.com"

    # Ollama settings
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama-host:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:latest")
    assert get_setting("ollama_base_url") == "http://ollama-host:11434"
    assert get_setting("ollama_model") == "qwen2.5:latest"


# ── DeepSeek Direct Provider Tests ─────────────────────────────────────────────


def test_deepseek_requires_key():
    with pytest.raises(LLMAuthenticationError, match="No API key for DeepSeek"):
        DeepSeekProvider(api_key="")


def test_deepseek_successful_request():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return json_reply('{"clips": [{"rank": 1, "title": "Great clip"}]}')

    provider = DeepSeekProvider(
        api_key="sk-deepseek-secret",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    result = provider.complete_json("system instructions", "user transcript", {}, "test_schema")

    assert result == {"clips": [{"rank": 1, "title": "Great clip"}]}
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer sk-deepseek-secret"
    assert captured["body"]["model"] == "deepseek-chat"
    # DeepSeek must use {"type": "json_object"} rather than json_schema on the first attempt
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_deepseek_fallback_behavior():
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append(body.get("response_format"))
        if "response_format" in body:
            err = {"message": "Invalid response_format parameter", "type": "invalid_request_error"}
            return httpx.Response(400, json={"error": err})
        return json_reply('{"clips": [{"rank": 1, "title": "Fallback clip"}]}')

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    result = provider.complete_json("system instructions", "user transcript", {}, "test_schema")
    assert result == {"clips": [{"rank": 1, "title": "Fallback clip"}]}
    assert len(calls) == 2
    assert calls[0] == {"type": "json_object"}
    assert calls[1] is None


def test_deepseek_400_non_format_error():
    def handler(_):
        return httpx.Response(
            400,
            json={"error": {"message": "Invalid prompt length", "type": "invalid_request_error"}},
        )

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMError, match="Invalid prompt length"):
        provider.complete_json("s", "u", {}, "n")


def test_deepseek_malformed_or_multiple_json_causes_controlled_retry():
    attempt_prompts = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        user_prompt = body["messages"][-1]["content"]
        attempt_prompts.append(user_prompt)

        if len(attempt_prompts) == 1:
            # First attempt returns multiple JSON objects (like the error in production)
            return json_reply('{"clips": []}\n{"clips": []}')
        # Second attempt returns valid JSON
        return json_reply('{"clips": [{"rank": 1, "start_seconds": 0.0, "end_seconds": 25.0}]}')

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )

    transcript = {
        "language": "en",
        "sentences": [{"start": 0.0, "end": 30.0, "text": "hello world"}],
    }
    options = {"clip_count": 1, "min_seconds": 15.0, "max_seconds": 30.0}

    result = select_clips(provider, {"title": "Test"}, transcript, options)
    assert len(result["clips"]) == 1
    assert result["clips"][0]["start_seconds"] == 0.0
    assert result["clips"][0]["end_seconds"] == 30.0  # snapped to sentence boundary
    assert len(attempt_prompts) == 2
    # Verify the corrective prompt explicitly instructed the model about formatting
    assert "returned invalid JSON" in attempt_prompts[1]
    assert "CRITICAL FORMATTING INSTRUCTIONS" in attempt_prompts[1]


def test_openrouter_sends_json_schema():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return json_reply('{"clips": []}')

    provider = OpenRouterProvider(
        api_key="sk-or-test",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = provider.complete_json("sys", "user", {"type": "object"}, "clip_schema")
    assert result == {"clips": []}
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["name"] == "clip_schema"


def test_deepseek_authentication_error():
    def handler(_):
        return httpx.Response(401, json={"error": {"message": "Authentication failed: invalid key"}})

    provider = DeepSeekProvider(
        api_key="bad-key",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMAuthenticationError, match="authentication failed"):
        provider.complete_json("s", "u", {}, "n")


def test_deepseek_rate_limit_error():
    def handler(_):
        return httpx.Response(429, json={"error": {"message": "Insufficient balance or rate limit"}})

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMRateLimitError, match="rate limit or quota exceeded"):
        provider.complete_json("s", "u", {}, "n")


def test_deepseek_model_not_found():
    def handler(_):
        return httpx.Response(404, json={"error": {"message": "Model 'bad-model' does not exist"}})

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="bad-model",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMModelNotFoundError, match="not found"):
        provider.complete_json("s", "u", {}, "n")


def test_deepseek_malformed_json_error():
    def handler(_):
        return json_reply("I cannot find clips: Sorry!")

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMStructuredOutputError, match="Model did not return JSON"):
        provider.complete_json("s", "u", {}, "n")


def test_deepseek_list_models():
    def handler(_):
        return httpx.Response(
            200,
            json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]},
        )

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    models = provider.list_models()
    assert [m["id"] for m in models] == ["deepseek-chat", "deepseek-reasoner"]


def test_deepseek_test_connection():
    def handler(_):
        return json_reply('{"ok": true}')

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    res = provider.test_connection()
    assert res["ok"] is True
    assert res["provider"] == "deepseek"
    assert res["model"] == "deepseek-chat"


# ── Ollama Provider Tests ─────────────────────────────────────────────────────


def test_ollama_successful_request():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return json_reply('{"clips": [{"rank": 1, "title": "Local clip"}]}')

    provider = OllamaProvider(
        model="llama3.2",
        base_url="http://localhost:11434",
        transport=httpx.MockTransport(handler),
    )
    result = provider.complete_json("system instructions", "user transcript", {}, "schema")

    assert result == {"clips": [{"rank": 1, "title": "Local clip"}]}
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["body"]["model"] == "llama3.2"


def test_ollama_unavailable_raises_connection_error():
    def handler(_):
        raise httpx.ConnectError("Connection refused")

    provider = OllamaProvider(
        model="llama3.2",
        base_url="http://localhost:11434",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMConnectionError, match="Unable to connect to Ollama"):
        provider.complete_json("s", "u", {}, "n")


def test_ollama_list_models():
    def handler(request: httpx.Request):
        if str(request.url).endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5:latest"}]},
            )
        return httpx.Response(404)

    provider = OllamaProvider(
        model="llama3.2",
        transport=httpx.MockTransport(handler),
    )
    models = provider.list_models()
    assert [m["id"] for m in models] == ["llama3.2:latest", "qwen2.5:latest"]


def test_ollama_test_connection_success():
    def handler(request: httpx.Request):
        if "/api/tags" in str(request.url):
            return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})
        return json_reply('{"ok": true}')

    provider = OllamaProvider(
        model="llama3.2",
        transport=httpx.MockTransport(handler),
    )
    res = provider.test_connection()
    assert res["ok"] is True
    assert res["provider"] == "ollama"


def test_ollama_test_connection_missing_model():
    def handler(request: httpx.Request):
        if "/api/tags" in str(request.url):
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:latest"}]})
        return json_reply('{"ok": true}')

    provider = OllamaProvider(
        model="missing-model",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMModelNotFoundError, match="ollama pull missing-model"):
        provider.test_connection()


# ── Pipeline Integration Tests ────────────────────────────────────────────────


def test_pipeline_select_clips_with_deepseek(transcript):
    clip_data = {
        "clips": [
            {
                "rank": 1,
                "start_seconds": 6.0,
                "end_seconds": 23.0,
                "title": "DeepSeek Clip",
                "post_title": "DeepSeek Short",
                "caption": "Check this moment out",
                "hashtags": ["#ai", "#viral"],
                "broll_queries": ["coding"],
                "rationale": "High hook",
                "hook_score": 9.0,
                "value_score": 8.5,
                "clarity_score": 9.0,
                "overall_score": 8.8,
            }
        ]
    }

    def handler(_):
        return json_reply(json.dumps(clip_data))

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )

    options = {"clip_count": 1, "min_seconds": 15, "max_seconds": 30, "instructions": ""}
    result = select_clips(provider, {"title": "Test Video"}, transcript, options)

    assert result["model"] == "deepseek-chat"
    assert len(result["clips"]) == 1
    clip = result["clips"][0]
    assert clip["title"] == "DeepSeek Clip"
    assert clip["start_seconds"] == 6.0
    assert clip["end_seconds"] > clip["start_seconds"]
    assert clip["hashtags"] == ["#ai", "#viral"]


def test_pipeline_select_clips_with_ollama(transcript):
    clip_data = {
        "clips": [
            {
                "rank": 1,
                "start_seconds": 6.0,
                "end_seconds": 23.0,
                "title": "Ollama Clip",
                "post_title": "Ollama Short",
                "caption": "Local model insight",
                "hashtags": ["#local", "#offline"],
                "broll_queries": ["server"],
                "rationale": "Strong point",
                "hook_score": 8.5,
                "value_score": 8.0,
                "clarity_score": 8.5,
                "overall_score": 8.3,
            }
        ]
    }

    def handler(_):
        return json_reply(json.dumps(clip_data))

    provider = OllamaProvider(
        model="llama3.2",
        transport=httpx.MockTransport(handler),
    )

    options = {"clip_count": 1, "min_seconds": 15, "max_seconds": 30, "instructions": ""}
    result = select_clips(provider, {"title": "Test Video"}, transcript, options)

    assert result["model"] == "llama3.2"
    assert len(result["clips"]) == 1
    assert result["clips"][0]["title"] == "Ollama Clip"


# ── Top-level functions ────────────────────────────────────────────────────────


def test_top_level_helpers(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    db.set_setting("llm_provider", "deepseek")
    db.set_setting("deepseek_api_key", "sk-ds")
    db.set_setting("deepseek_model", "deepseek-chat")

    llm = get_llm()
    assert isinstance(llm, DeepSeekProvider)
    assert llm.model == "deepseek-chat"

    # Override model
    llm_override = get_llm(model="deepseek-reasoner")
    assert llm_override.model == "deepseek-reasoner"


def test_deepseek_timeout():
    def handler(_):
        raise httpx.TimeoutException("timed out")

    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMTimeoutError, match="timed out"):
        provider.complete_json("s", "u", {}, "n")


def test_top_level_list_models_and_connection(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    db.set_setting("llm_provider", "deepseek")
    db.set_setting("deepseek_api_key", "sk-ds")

    def handler(request: httpx.Request):
        if "/models" in str(request.url):
            return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}]})
        return json_reply('{"ok": true}')

    res = do_test_connection(
        provider="deepseek",
        transport=httpx.MockTransport(handler),
    )
    assert res["ok"] is True
    assert res["provider"] == "deepseek"

    # list_models with custom transport provider
    provider = DeepSeekProvider(
        api_key="sk-test",
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )
    models = provider.list_models()
    assert len(models) >= 1
