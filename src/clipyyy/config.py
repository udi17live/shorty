"""Paths and settings.

Settings are stored in the local SQLite database so they can be edited from the UI or the
CLI. Environment variables act as fallbacks, which is handy for Docker and CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def home() -> Path:
    """Root folder for the database, runs and model caches (``CLIPYYY_HOME``)."""
    path = Path(os.environ.get("CLIPYYY_HOME", Path.home() / ".clipyyy")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def runs_dir() -> Path:
    return home() / "runs"


def uploads_dir() -> Path:
    return home() / "uploads"


@dataclass(frozen=True, slots=True)
class SettingSpec:
    env: str
    default: str = ""
    secret: bool = False
    description: str = ""
    fallback_envs: tuple[str, ...] = ()


SETTINGS: dict[str, SettingSpec] = {
    "llm_provider": SettingSpec(
        "LLM_PROVIDER",
        "openrouter",
        description="Active LLM provider (deepseek, openrouter, ollama)",
        fallback_envs=("CLIPYYY_LLM_PROVIDER",),
    ),
    "openrouter_api_key": SettingSpec(
        "OPENROUTER_API_KEY",
        secret=True,
        description="OpenRouter API key",
        fallback_envs=("CLIPYYY_OPENROUTER_API_KEY",),
    ),
    "openrouter_base_url": SettingSpec(
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
        description="OpenRouter base URL",
        fallback_envs=("CLIPYYY_OPENROUTER_BASE_URL",),
    ),
    "openrouter_model": SettingSpec(
        "OPENROUTER_MODEL",
        "",
        description="OpenRouter model (overrides default model)",
        fallback_envs=("CLIPYYY_OPENROUTER_MODEL",),
    ),
    "deepseek_api_key": SettingSpec(
        "DEEPSEEK_API_KEY",
        secret=True,
        description="DeepSeek API key",
        fallback_envs=("CLIPYYY_DEEPSEEK_API_KEY",),
    ),
    "deepseek_base_url": SettingSpec(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
        description="DeepSeek API base URL",
        fallback_envs=("CLIPYYY_DEEPSEEK_BASE_URL",),
    ),
    "deepseek_model": SettingSpec(
        "DEEPSEEK_MODEL",
        "deepseek-chat",
        description="DeepSeek model name",
        fallback_envs=("CLIPYYY_DEEPSEEK_MODEL",),
    ),
    "ollama_base_url": SettingSpec(
        "OLLAMA_BASE_URL",
        "http://localhost:11434",
        description="Ollama server base URL",
        fallback_envs=("CLIPYYY_OLLAMA_BASE_URL",),
    ),
    "ollama_model": SettingSpec(
        "OLLAMA_MODEL",
        "llama3.2",
        description="Ollama model name",
        fallback_envs=("CLIPYYY_OLLAMA_MODEL",),
    ),
    "llm_model": SettingSpec(
        "CLIPYYY_LLM_MODEL",
        "google/gemini-3.8-flash",
        description="Default model used to pick clips",
        fallback_envs=("LLM_MODEL", "OPENROUTER_MODEL"),
    ),
    "whisper_model": SettingSpec("CLIPYYY_WHISPER_MODEL", "small", description="faster-whisper model size"),
    "pexels_api_key": SettingSpec("PEXELS_API_KEY", secret=True, description="Pexels key for B-roll"),
    "buffer_api_key": SettingSpec("BUFFER_API_KEY", secret=True, description="Buffer API key"),
    "buffer_organization_id": SettingSpec(
        "BUFFER_ORGANIZATION_ID", description="Buffer organization (auto-picked if you have one)"
    ),
    "s3_endpoint_url": SettingSpec(
        "CLIPYYY_S3_ENDPOINT_URL", description="S3-compatible endpoint (R2, B2, MinIO). Empty for AWS"
    ),
    "s3_region": SettingSpec("CLIPYYY_S3_REGION", "auto", description="S3 region"),
    "s3_bucket": SettingSpec("CLIPYYY_S3_BUCKET", description="Bucket that hosts clips for Buffer"),
    "s3_access_key_id": SettingSpec("CLIPYYY_S3_ACCESS_KEY_ID", secret=True, description="S3 key id"),
    "s3_secret_access_key": SettingSpec("CLIPYYY_S3_SECRET_ACCESS_KEY", secret=True, description="S3 secret"),
    "s3_public_base_url": SettingSpec(
        "CLIPYYY_S3_PUBLIC_BASE_URL",
        description="Public URL of the bucket. Empty uses 7-day signed links",
    ),
    "ytdlp_cookies_from_browser": SettingSpec(
        "CLIPYYY_COOKIES_FROM_BROWSER",
        description="Browser whose YouTube login yt-dlp may use (chrome, firefox, brave, edge...)",
    ),
    "ytdlp_cookies_file": SettingSpec(
        "CLIPYYY_COOKIES_FILE", description="Path to a cookies.txt file, used instead of a browser"
    ),
    "default_instructions": SettingSpec(
        "CLIPYYY_DEFAULT_INSTRUCTIONS",
        description="Extra guidance added to every clip-selection prompt (tone, CTA, audience)",
    ),
}


def get_setting(key: str) -> str:
    """Database value, then environment variable, then default."""
    from clipyyy import db

    if key not in SETTINGS:
        return ""
    spec = SETTINGS[key]
    value = db.get_setting(key)
    if value and value.strip():
        return value.strip()
    val = os.environ.get(spec.env, "").strip()
    if val:
        return val
    for alt in spec.fallback_envs:
        alt_val = os.environ.get(alt, "").strip()
        if alt_val:
            return alt_val
    return spec.default


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}••••{value[-4:]}"
