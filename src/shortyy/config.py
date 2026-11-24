"""Paths and settings.

Settings are stored in the local SQLite database so they can be edited from the UI or the
CLI. Environment variables act as fallbacks, which is handy for Docker and CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def load_dotenv_if_present(path: Path | None = None) -> None:
    """Load key=value pairs from a local .env file without overriding existing env vars."""
    if os.environ.get("SHORTYY_NO_DOTENV") or os.environ.get("CLIPYYY_NO_DOTENV"):
        return
    env_file = path or (Path.cwd() / ".env")
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
            val = val[1:-1]
        if key:
            os.environ.setdefault(key, val)


def home() -> Path:
    """Root folder for the database, runs and model caches (``SHORTYY_HOME``)."""
    configured = os.environ.get("SHORTYY_HOME") or os.environ.get("CLIPYYY_HOME")
    path = Path(configured).expanduser() if configured else (Path.home() / ".shortyy")
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    """Configured SQLAlchemy database URL (PostgreSQL in Docker/prod, SQLite fallback locally)."""
    explicit = os.environ.get("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    base = home()
    db_path = base / "shortyy.db"
    legacy_path = base / "clipyyy.db"
    if not db_path.exists() and legacy_path.is_file():
        db_path = legacy_path
    return f"sqlite:///{db_path}"


def is_postgres_url(url: str) -> bool:
    return url.startswith("postgresql")


def get_oauth_encryption_key() -> str:
    return os.environ.get("OAUTH_ENCRYPTION_KEY", "").strip()


def get_google_oauth_config() -> tuple[str, str, str]:
    """Return ``(client_id, client_secret, redirect_uri)`` from environment variables."""
    return (
        os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip(),
    )


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
        fallback_envs=("SHORTYY_LLM_PROVIDER", "CLIPYYY_LLM_PROVIDER"),
    ),
    "openrouter_api_key": SettingSpec(
        "OPENROUTER_API_KEY",
        secret=True,
        description="OpenRouter API key",
        fallback_envs=("SHORTYY_OPENROUTER_API_KEY", "CLIPYYY_OPENROUTER_API_KEY"),
    ),
    "openrouter_base_url": SettingSpec(
        "OPENROUTER_BASE_URL",
        "https://openrouter.ai/api/v1",
        description="OpenRouter base URL",
        fallback_envs=("SHORTYY_OPENROUTER_BASE_URL", "CLIPYYY_OPENROUTER_BASE_URL"),
    ),
    "openrouter_model": SettingSpec(
        "OPENROUTER_MODEL",
        "",
        description="OpenRouter model (overrides default model)",
        fallback_envs=("SHORTYY_OPENROUTER_MODEL", "CLIPYYY_OPENROUTER_MODEL"),
    ),
    "deepseek_api_key": SettingSpec(
        "DEEPSEEK_API_KEY",
        secret=True,
        description="DeepSeek API key",
        fallback_envs=("SHORTYY_DEEPSEEK_API_KEY", "CLIPYYY_DEEPSEEK_API_KEY"),
    ),
    "deepseek_base_url": SettingSpec(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
        description="DeepSeek API base URL",
        fallback_envs=("SHORTYY_DEEPSEEK_BASE_URL", "CLIPYYY_DEEPSEEK_BASE_URL"),
    ),
    "deepseek_model": SettingSpec(
        "DEEPSEEK_MODEL",
        "deepseek-chat",
        description="DeepSeek model name",
        fallback_envs=("SHORTYY_DEEPSEEK_MODEL", "CLIPYYY_DEEPSEEK_MODEL"),
    ),
    "ollama_base_url": SettingSpec(
        "OLLAMA_BASE_URL",
        "http://localhost:11434",
        description="Ollama server base URL",
        fallback_envs=("SHORTYY_OLLAMA_BASE_URL", "CLIPYYY_OLLAMA_BASE_URL"),
    ),
    "ollama_model": SettingSpec(
        "OLLAMA_MODEL",
        "llama3.2",
        description="Ollama model name",
        fallback_envs=("SHORTYY_OLLAMA_MODEL", "CLIPYYY_OLLAMA_MODEL"),
    ),
    "llm_model": SettingSpec(
        "SHORTYY_LLM_MODEL",
        "google/gemini-3.8-flash",
        description="Default model used to pick clips",
        fallback_envs=("CLIPYYY_LLM_MODEL", "LLM_MODEL", "OPENROUTER_MODEL"),
    ),
    "whisper_model": SettingSpec(
        "SHORTYY_WHISPER_MODEL",
        "small",
        description="faster-whisper model size",
        fallback_envs=("CLIPYYY_WHISPER_MODEL",),
    ),
    "pexels_api_key": SettingSpec("PEXELS_API_KEY", secret=True, description="Pexels key for B-roll"),
    "buffer_api_key": SettingSpec("BUFFER_API_KEY", secret=True, description="Buffer API key"),
    "buffer_organization_id": SettingSpec(
        "BUFFER_ORGANIZATION_ID", description="Buffer organization (auto-picked if you have one)"
    ),
    "s3_endpoint_url": SettingSpec(
        "SHORTYY_S3_ENDPOINT_URL",
        description="S3-compatible endpoint (R2, B2, MinIO). Empty for AWS",
        fallback_envs=("CLIPYYY_S3_ENDPOINT_URL",),
    ),
    "s3_region": SettingSpec(
        "SHORTYY_S3_REGION",
        "auto",
        description="S3 region",
        fallback_envs=("CLIPYYY_S3_REGION",),
    ),
    "s3_bucket": SettingSpec(
        "SHORTYY_S3_BUCKET",
        description="Bucket that hosts clips for Buffer",
        fallback_envs=("CLIPYYY_S3_BUCKET",),
    ),
    "s3_access_key_id": SettingSpec(
        "SHORTYY_S3_ACCESS_KEY_ID",
        secret=True,
        description="S3 key id",
        fallback_envs=("CLIPYYY_S3_ACCESS_KEY_ID",),
    ),
    "s3_secret_access_key": SettingSpec(
        "SHORTYY_S3_SECRET_ACCESS_KEY",
        secret=True,
        description="S3 secret",
        fallback_envs=("CLIPYYY_S3_SECRET_ACCESS_KEY",),
    ),
    "s3_public_base_url": SettingSpec(
        "SHORTYY_S3_PUBLIC_BASE_URL",
        description="Public URL of the bucket. Empty uses 7-day signed links",
        fallback_envs=("CLIPYYY_S3_PUBLIC_BASE_URL",),
    ),
    "ytdlp_cookies_from_browser": SettingSpec(
        "SHORTYY_COOKIES_FROM_BROWSER",
        description="Browser whose YouTube login yt-dlp may use (chrome, firefox, brave, edge...)",
        fallback_envs=("CLIPYYY_COOKIES_FROM_BROWSER",),
    ),
    "ytdlp_cookies_file": SettingSpec(
        "SHORTYY_COOKIES_FILE",
        description="Path to a cookies.txt file, used instead of a browser",
        fallback_envs=("CLIPYYY_COOKIES_FILE",),
    ),
    "default_instructions": SettingSpec(
        "SHORTYY_DEFAULT_INSTRUCTIONS",
        description="Extra guidance added to every clip-selection prompt (tone, CTA, audience)",
        fallback_envs=("CLIPYYY_DEFAULT_INSTRUCTIONS",),
    ),
}


def get_setting(key: str) -> str:
    """Database value, then environment variable, then default."""
    from shortyy import db

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
