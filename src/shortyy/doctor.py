"""Environment checks shared by `shortyy doctor` and the UI."""

from __future__ import annotations

from shortyy.config import get_setting
from shortyy.database import check_database_connection
from shortyy.media import find_ffmpeg, install_hint
from shortyy.platforms import PlatformConnectorFactory
from shortyy.publish import storage_configured
from shortyy.source import js_runtime


def _llm_check() -> tuple[bool, str]:
    provider = (get_setting("llm_provider") or "openrouter").lower().strip()
    if provider == "deepseek":
        key = get_setting("deepseek_api_key")
        model = get_setting("deepseek_model") or "deepseek-chat"
        return (
            bool(key),
            f"deepseek · {model}" if key else "add a DeepSeek API key to find clips",
        )
    if provider == "ollama":
        base_url = get_setting("ollama_base_url") or "http://localhost:11434"
        model = get_setting("ollama_model") or "llama3.2"
        return True, f"ollama · {model} ({base_url})"

    # openrouter and default
    key = get_setting("openrouter_api_key")
    model = get_setting("openrouter_model") or get_setting("llm_model") or "google/gemini-3.8-flash"
    return (
        bool(key),
        f"openrouter · {model}" if key else "add an OpenRouter API key to find clips",
    )


def checks() -> list[dict]:
    found = find_ffmpeg()
    ffmpeg, libass = found.ffmpeg, found.libass
    llm_ok, llm_detail = _llm_check()
    runtime = js_runtime()
    db_ok, db_detail = check_database_connection()
    yt_ok, yt_detail = PlatformConnectorFactory.get_connector("youtube").is_configured()
    return [
        _check("database", db_ok, True, db_detail),
        _check(
            "ffmpeg",
            bool(ffmpeg and found.ffprobe),
            True,
            ffmpeg if ffmpeg and found.ffprobe else f"ffmpeg and ffprobe not found. {install_hint()}",
        ),
        _check(
            "captions",
            libass,
            True,
            "ffmpeg has libass"
            if libass
            else f"this ffmpeg can't draw captions (it has no libass). {install_hint()}",
        ),
        _check(
            "downloads",
            bool(runtime),
            False,
            f"yt-dlp uses {runtime.split(':')[0]} for YouTube"
            if runtime
            else "install deno or node so YouTube downloads work reliably",
        ),
        _check(
            "llm",
            llm_ok,
            True,
            llm_detail,
        ),
        _check(
            "broll",
            bool(get_setting("pexels_api_key")),
            False,
            "Pexels key set" if get_setting("pexels_api_key") else "optional: add a Pexels key",
        ),
        _check(
            "buffer",
            bool(get_setting("buffer_api_key")),
            False,
            "Buffer key set" if get_setting("buffer_api_key") else "optional: add a Buffer key",
        ),
        _check(
            "storage",
            storage_configured(),
            False,
            "S3 storage set" if storage_configured() else "optional: needed to publish to Buffer",
        ),
        _check(
            "youtube_oauth",
            yt_ok,
            False,
            "Google OAuth & encryption ready" if yt_ok else f"optional: {yt_detail}",
        ),
    ]


LABELS = {
    "database": "Database",
    "ffmpeg": "FFmpeg",
    "captions": "Captions",
    "downloads": "YouTube downloads",
    "llm": "AI model",
    "broll": "B-roll",
    "buffer": "Buffer",
    "storage": "Storage",
    "youtube_oauth": "YouTube OAuth",
}


def _check(name: str, ok: bool, required: bool, detail: str) -> dict:
    return {"name": name, "label": LABELS[name], "ok": ok, "required": required, "detail": detail}
