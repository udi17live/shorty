---
name: shortyy
description: Turn a long video, podcast or YouTube link into short vertical clips with captions using the shortyy CLI. Use when the user asks to clip a video, make shorts/reels/TikToks from a long video, or find the best moments in a recording.
---

# shortyy

shortyy is a local CLI that downloads or reads a video, transcribes it, asks an LLM to pick the best moments, and renders vertical clips with animated captions.

## Before the first run

```bash
shortyy doctor --json
```

Every check with `"required": true` must be `"ok": true`. If the `llm` check fails, configure one of the supported providers:

```bash
# DeepSeek Direct API
shortyy config set llm_provider deepseek
shortyy config set deepseek_api_key <key>

# Or OpenRouter
shortyy config set llm_provider openrouter
shortyy config set openrouter_api_key <key>

# Or local Ollama
shortyy config set llm_provider ollama
shortyy config set ollama_model llama3.2
```

Never print or log keys.

## Make clips

```bash
shortyy clip "<url or file path>" --json --out <folder>
```

Useful options:

- `--count N` maximum clips (default 3, up to 10)
- `--min S --max S` clip length in seconds (default 20 and 60)
- `--aspect 9:16|4:5|1:1`
- `--style bold|highlight|minimal`, or `--no-captions`
- `--broll` (needs a Pexels key), `--no-face-tracking`
- `--language en` to skip language detection
- `--instructions "..."` to steer the selection, for example "funny moments only" or "end captions with Follow for part 2"
- `--provider deepseek|openrouter|ollama` to override the LLM provider
- `--model <model-id>` to override the model (e.g. `deepseek-chat`, `google/gemini-3.8-flash`, `llama3.2`)

The command runs in the foreground; long videos take several minutes, mostly for transcription. Progress lines go to stderr and the result is JSON on stdout:

```json
{"run_id": "…", "status": "completed", "clips": [{"id": "…", "rank": 1, "title": "…", "post_title": "…", "caption": "…", "hashtags": ["#…"], "duration_seconds": 41.2, "file": "/abs/path/clip-01-….mp4"}]}
```

The exit code is 0 when the run completed. If it failed, `error` names the stage. Fix the cause and resume without starting over:

```bash
shortyy retry <run_id> --json
shortyy retry <run_id> --from select --json   # pick different clips, keep the transcript
```

## Other commands

- `shortyy runs --json` and `shortyy show <run_id> --json`
- `shortyy models <search> --json` lists models that support structured output
- `shortyy channels --json` and `shortyy publish <clip_id> --channel <id> --mode queue|schedule|now|draft [--at ISO]` publish through Buffer

Publishing posts to the user's real social accounts. Only run `shortyy publish` when the user has explicitly asked to post that clip to those channels.
