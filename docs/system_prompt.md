# Clipyyy — Refactor LLM Integration into a Provider/Driver Architecture

You are working on my fork of the open-source `clipyyy` repository.

## Goal

Refactor the existing LLM integration so that Clipyyy is **LLM-provider agnostic**.

I do NOT want OpenRouter hard-coded throughout the application.

I want a clean **provider/driver/factory architecture** where I can select which LLM provider to use from configuration, without changing the rest of the clipping pipeline.

The immediate providers to support are:

1. **DeepSeek Direct API**
2. **OpenRouter**
3. **Ollama/local models**

The architecture must make it easy to add future providers such as OpenAI, Anthropic, Google Gemini, etc.

The existing Clipyyy functionality must continue working exactly as it does today.

---

# 1. First inspect the existing codebase

Before making changes:

- Inspect the entire repository structure.
- Read `AGENTS.md`.
- Inspect `src/clipyyy`.
- Identify exactly where:
  - LLM configuration is defined
  - OpenRouter API calls are made
  - models are selected
  - structured output is requested
  - clip selection prompts are built
  - title/caption/hashtag generation happens
  - settings are stored
  - frontend settings are implemented
  - CLI configuration is implemented
  - environment variables are loaded
  - tests exist for LLM functionality

Do not rewrite unrelated code.

Preserve the existing architecture wherever practical.

---

# 2. Create a proper LLM provider abstraction

Introduce an interface/abstract base class along the lines of:

```python
class LLMProvider(ABC):
    async def generate(...)
    async def generate_structured(...)
    async def list_models(...)
```

Use the appropriate existing async/sync patterns from the project rather than forcing an incompatible architecture.

The important requirement is:

**The rest of Clipyyy must not know whether the model is DeepSeek, OpenRouter, Ollama, etc.**

The clip-selection pipeline should depend on the provider interface.

For example:

```text
Clip Selection Pipeline
        │
        ▼
   LLMProvider
        │
        ├── DeepSeekProvider
        ├── OpenRouterProvider
        └── OllamaProvider
```

---

# 3. Implement an LLM Provider Factory

Create a factory/resolver such as:

```python
LLMProviderFactory.create(config)
```

or an equivalent clean implementation appropriate to the existing project.

It should select the implementation based on configuration:

```text
provider = deepseek
provider = openrouter
provider = ollama
```

Do NOT scatter checks like this throughout the code:

```python
if provider == "deepseek":
    ...
elif provider == "openrouter":
    ...
```

Provider-specific logic belongs inside the provider implementations/factory.

---

# 4. DeepSeek DIRECT API support

Add native Direct DeepSeek API support.

Do NOT route DeepSeek through OpenRouter.

Use DeepSeek's official OpenAI-compatible API:

```text
https://api.deepseek.com
```

The configuration should support:

```env
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=...
```

The base URL must be configurable even though the default is:

```text
https://api.deepseek.com
```

This allows future compatibility with compatible gateways/proxies.

Use the OpenAI-compatible API correctly rather than implementing a custom HTTP protocol unnecessarily.

---

# 5. OpenRouter support

Preserve the existing OpenRouter functionality.

Existing users should be able to configure:

```env
OPENROUTER_API_KEY=...
```

and:

```env
CLIPYYY_LLM_MODEL=...
```

or whatever configuration structure already exists.

Do not break the existing OpenRouter path.

Existing OpenRouter model identifiers such as:

```text
provider/model
```

must continue working.

---

# 6. Ollama support

Add an Ollama provider.

Default:

```text
http://localhost:11434
```

Configuration should support:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=...
```

The provider must communicate with Ollama without requiring a cloud API key.

This should allow models such as:

```text
qwen
llama
deepseek
gemma
```

or whatever models the user has installed locally.

Do not hard-code a specific Ollama model.

---

# 7. Unified model configuration

Introduce a provider-aware configuration model.

For example:

```text
LLM_PROVIDER=deepseek
LLM_MODEL=...
```

Then provider-specific credentials/settings:

```text
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL

OPENROUTER_API_KEY

OLLAMA_BASE_URL
```

Prefer a clean configuration structure rather than forcing everything into one ambiguous variable.

Backward compatibility with the existing Clipyyy configuration is important.

Existing installations using OpenRouter should continue to work without requiring a major migration.

---

# 8. Web UI

Update the existing Clipyyy Settings UI.

Add an **LLM Provider** selector.

Example:

```text
AI Provider
[ DeepSeek ▼ ]

Model
[ deepseek model ▼ ]

API Key
[ *************** ]

Base URL
[ https://api.deepseek.com ]
```

Provider options:

```text
DeepSeek
OpenRouter
Ollama
```

When the provider changes:

### DeepSeek

Show:

```text
API Key
Model
Base URL
```

Default base URL:

```text
https://api.deepseek.com
```

### OpenRouter

Show:

```text
API Key
Model
```

### Ollama

Show:

```text
Base URL
Model
```

Do not show irrelevant fields.

The UI must clearly indicate which provider is currently active.

---

# 9. Model selection

If practical within the existing architecture, allow the user to:

```text
Provider → Model
```

For example:

```text
DeepSeek
  ├── model A
  ├── model B
  └── model C
```

Do not hard-code outdated DeepSeek model names.

If the provider supports model listing, implement model discovery.

If model discovery is unavailable, allow manual model entry.

The application must not break when a newer model becomes available.

---

# 10. Provider test button

Add a UI action such as:

```text
[Test connection]
```

When clicked:

- verify credentials
- verify the base URL
- verify the model
- perform a minimal test request
- return a clear success/failure message

Examples:

```text
✓ DeepSeek connection successful
Model: <model>

or

✗ DeepSeek connection failed
Reason: Invalid API key
```

Do not expose API keys in logs or error messages.

---

# 11. CLI support

Preserve the existing CLI functionality.

Add provider configuration through the CLI if the existing configuration system supports it.

For example, support something equivalent to:

```bash
clipyyy config set llm_provider deepseek
clipyyy config set deepseek_api_key sk-...
clipyyy config set deepseek_model ...
```

Also support:

```bash
clipyyy config set llm_provider openrouter
```

and:

```bash
clipyyy config set llm_provider ollama
```

Do not break existing commands.

The existing:

```bash
clipyyy clip ...
```

workflow must work regardless of the selected provider.

---

# 12. Environment variable support

Support environment variables for Docker/headless automation.

Example:

```env
LLM_PROVIDER=deepseek

DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=...

OPENROUTER_API_KEY=...

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=...
```

Environment variable names should follow the existing Clipyyy naming conventions where possible.

Document all new variables.

---

# 13. Secret handling

Never expose API keys in:

- logs
- API responses
- frontend source
- exception messages
- generated JSON
- debug output

Mask keys in the UI.

Follow the existing Clipyyy secret-storage mechanism where possible.

If Clipyyy stores credentials in SQLite/configuration storage, integrate with that mechanism rather than creating an unrelated secret system.

---

# 14. Preserve structured output

This is extremely important.

The current clip-selection system relies on structured LLM output.

The new provider abstraction must preserve:

- JSON/structured responses
- clip ranking
- start/end timestamps
- title
- caption
- hashtags
- B-roll ideas where applicable
- all existing metadata

Do NOT simplify the LLM call to plain text.

If a provider has different structured-output capabilities, implement the appropriate compatibility layer.

The rest of the application should receive the same internal data structure regardless of provider.

---

# 15. Preserve existing prompts

Do NOT rewrite the existing clip-selection prompts unless necessary.

The provider abstraction should sit underneath the existing prompting logic.

Existing prompt behavior should remain unchanged.

The purpose of this task is to change **which LLM is used**, not to change Clipyyy's clipping intelligence.

---

# 16. DeepSeek-specific optimization

Make DeepSeek work well for Clipyyy's use case.

The primary task is:

```text
Long transcript
      ↓
DeepSeek
      ↓
Rank the best standalone moments
      ↓
Return structured clip metadata
```

The model should receive the transcript and existing Clipyyy instructions in the same general way the current OpenRouter implementation does.

Do not send the video itself to DeepSeek.

Videos remain local.

Only the necessary text/model request data should be sent to the configured LLM provider.

---

# 17. Error handling

Implement provider-specific errors cleanly.

Examples:

```text
Invalid API key
Model not found
Insufficient credits
Rate limited
Network unavailable
Invalid structured response
Timeout
Ollama unavailable
```

Convert provider-specific errors into useful application-level errors.

The UI should show useful messages rather than raw stack traces.

Retry transient failures where the existing application already has retry behavior.

Do not create infinite retry loops.

---

# 18. Automatic provider fallback

Do NOT automatically switch providers without the user's explicit configuration.

For example:

```text
DeepSeek fails
    ↓
Do NOT silently switch to OpenRouter
```

That could unexpectedly spend money.

If fallback support is implemented later, it must be explicitly configured.

For now, use exactly the selected provider.

---

# 19. Docker compatibility

The new architecture must work with the existing Docker setup.

The following should continue to work:

```bash
docker compose up -d
```

The web UI should remain available on the existing port.

DeepSeek should work from inside the Docker container.

Ollama should also be usable from Docker when configured correctly.

Document the correct host configuration for Ollama if necessary.

Do not require users to modify Docker manually for DeepSeek.

---

# 20. No unnecessary dependencies

Keep the implementation lightweight.

Before adding a dependency:

1. Check whether the project already has an equivalent dependency.
2. Prefer the existing HTTP/LLM client.
3. Reuse existing abstractions.
4. Avoid adding large frameworks.

Do not rewrite the application around LangChain or another framework unless the existing architecture already uses it.

This should remain a simple, maintainable FastAPI/Python application.

---

# 21. Tests

Add/modify tests for:

### Factory

```text
deepseek → DeepSeekProvider
openrouter → OpenRouterProvider
ollama → OllamaProvider
unknown → useful error
```

### Configuration

Test:

- provider selection
- API keys
- model
- base URLs
- defaults
- backward compatibility

### Provider requests

Mock HTTP requests.

Do NOT make real API calls during tests.

Test:

- successful response
- authentication failure
- rate limiting
- malformed structured output
- timeout
- unavailable provider

### Integration

Verify that the existing clip-selection pipeline can operate with each provider.

---

# 22. Backward compatibility

This is mandatory.

A user who currently has:

```env
OPENROUTER_API_KEY=...
```

should not have their existing installation unexpectedly break.

If no provider is explicitly configured, preserve the existing behavior where possible.

If the current behavior assumes OpenRouter, make OpenRouter the backwards-compatible default.

Existing CLI commands must continue working.

Existing saved settings must continue working.

Existing generated runs should remain readable.

---

# 23. Documentation

Update the README and relevant documentation.

Explain:

```text
LLM Providers
```

with examples for:

### DeepSeek

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

### OpenRouter

```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
CLIPYYY_LLM_MODEL=...
```

### Ollama

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=...
```

Explain how to change providers without modifying source code.

Explain how to use the UI.

Explain how to use Docker.

Explain how to test the connection.

---

# 24. Provider architecture must be extensible

The final architecture should make adding another provider easy.

A future developer should be able to create:

```text
AnthropicProvider
```

without modifying the clip-selection pipeline.

Ideally adding a provider should involve:

1. Implement provider class.
2. Register provider with factory.
3. Add configuration.
4. Add UI entry.
5. Add tests.

Avoid tight coupling.

---

# 25. Keep the existing video pipeline untouched

Do NOT rewrite:

- yt-dlp integration
- Whisper transcription
- MediaPipe face tracking
- FFmpeg rendering
- caption rendering
- B-roll functionality
- batch processing
- run persistence
- CLI architecture

unless required to integrate the provider abstraction.

The goal is specifically:

> **Replace hard-coded OpenRouter dependency with a pluggable LLM driver system.**

Everything else should continue behaving as before.

---

# 26. Future automation compatibility

The final implementation will eventually be used as an automated video-generation pipeline.

Therefore:

- CLI must remain fully functional.
- `--json` output must remain machine-readable.
- provider configuration must work headlessly.
- Docker must work without interactive setup.
- no browser interaction should be required to use DeepSeek.
- no provider-specific logic should leak into the automation pipeline.

I eventually want to be able to run something like:

```bash
clipyyy clip "YOUTUBE_URL" --count 1 --max 60 --json
```

using DeepSeek automatically.

The provider must therefore be completely transparent to the clipping pipeline.

---

# 27. Quality requirements

Before considering the task complete:

- Run the existing test suite.
- Add tests for the new provider architecture.
- Run linting/type checks used by the repository.
- Verify the frontend builds.
- Verify Docker builds.
- Verify the application starts.
- Verify the existing OpenRouter path still works through mocks.
- Verify DeepSeek configuration works through mocked API calls.
- Verify Ollama configuration works through mocked API calls.
- Verify the provider can be changed without changing source code.
- Verify secrets are not exposed.
- Update documentation.

Do not leave TODO placeholders.

Do not implement a fake provider.

Do not hard-code my API key.

Do not remove OpenRouter support.

Do not remove Ollama support.

---

# 28. Important implementation principle

Do not immediately start editing files.

First inspect the existing architecture and identify the minimum set of files that need to change.

Then implement the refactor incrementally.

At the end, give me:

1. A concise summary of the architecture you found.
2. The files you changed.
3. What was added.
4. How to configure DeepSeek.
5. How to configure OpenRouter.
6. How to configure Ollama.
7. How to switch providers.
8. How to run the tests.
9. Any architectural compromises or limitations.
10. Any remaining work that is genuinely necessary.

The finished result should feel like a **proper production-quality provider/driver system**, not a collection of `if provider == ...` hacks.

## Final desired user experience

I want this:

```text
Clipyyy Settings
        │
        ▼
AI Provider
        │
        ├── DeepSeek
        ├── OpenRouter
        └── Ollama
```

I select:

```text
DeepSeek
```

enter:

```text
API key
Model
```

click:

```text
Test Connection
```

then Clipyyy's existing clipping pipeline automatically uses DeepSeek.

Tomorrow I should be able to switch to OpenRouter or Ollama from Settings without changing the application code.

**Do not change the fundamental Clipyyy product. Make its LLM layer pluggable.**