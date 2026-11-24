"""SQLAlchemy engine, session management, Alembic migration helpers, and legacy SQLite import."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from shortyy.config import PACKAGE_DIR, database_url, home, is_postgres_url

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}
_migrated_urls: set[str] = set()


def _find_alembic_ini() -> Path:
    explicit = (
        os.environ.get("SHORTYY_ALEMBIC_INI", "").strip()
        or os.environ.get("CLIPYYY_ALEMBIC_INI", "").strip()
    )
    candidates = [
        Path(explicit) if explicit else None,
        Path.cwd() / "alembic.ini",
        PACKAGE_DIR.parent.parent / "alembic.ini",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise FileNotFoundError("Could not locate alembic.ini")


def get_engine(url: str | None = None) -> Engine:
    resolved = url or database_url()
    with _lock:
        engine = _engines.get(resolved)
        if engine is not None:
            return engine
        kwargs: dict = {"future": True}
        if resolved.startswith("sqlite"):
            kwargs["connect_args"] = {"timeout": 30, "check_same_thread": False}
        else:
            kwargs["pool_pre_ping"] = True
        engine = create_engine(resolved, **kwargs)
        if resolved.startswith("sqlite"):

            @event.listens_for(engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _connection_record) -> None:  # type: ignore[no-untyped-def]
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.close()

        _engines[resolved] = engine
        _session_factories[resolved] = sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False, class_=Session
        )
        return engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    resolved = url or database_url()
    get_engine(resolved)
    return _session_factories[resolved]


def run_migrations(url: str | None = None) -> None:
    """Apply pending Alembic migrations up to ``head``."""
    from alembic.config import Config

    from alembic import command

    resolved = url or database_url()
    ini_path = _find_alembic_ini()
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(ini_path.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", resolved)
    cfg.attributes["skip_logging_config"] = True
    command.upgrade(cfg, "head")
    with _lock:
        _migrated_urls.add(resolved)


def ensure_schema(url: str | None = None) -> None:
    """Ensure schema is migrated via Alembic (cached per database URL)."""
    resolved = url or database_url()
    with _lock:
        if resolved in _migrated_urls:
            return
        if is_postgres_url(resolved):
            # In PostgreSQL, verify migrations were applied rather than auto-creating tables.
            engine = get_engine(resolved)
            inspector = inspect(engine)
            if inspector.has_table("alembic_version") and inspector.has_table("projects"):
                _migrated_urls.add(resolved)
                return
            run_migrations(resolved)
            return
        run_migrations(resolved)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """Provide a transactional SQLAlchemy session scope."""
    resolved = url or database_url()
    ensure_schema(resolved)
    factory = get_session_factory(resolved)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database_connection(url: str | None = None) -> tuple[bool, str]:
    """Verify database connectivity for healthchecks and doctor."""
    resolved = url or database_url()
    try:
        engine = get_engine(resolved)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        backend = "postgresql" if is_postgres_url(resolved) else "sqlite"
        return True, f"{backend} connected"
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", exc)
        return False, "Database unavailable"


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def migrate_legacy_sqlite_if_needed(url: str | None = None) -> bool:
    """Import runs/stages/clips/posts/settings from legacy SQLite DB into an empty Postgres DB."""
    from shortyy.models import Clip, Post, Project, Run, Setting, Stage, utcnow

    resolved = url or database_url()
    if not is_postgres_url(resolved):
        return False
    base = home()
    legacy_path = base / "shortyy.db"
    if not legacy_path.is_file():
        legacy_path = base / "clipyyy.db"
    if not legacy_path.is_file():
        return False

    ensure_schema(resolved)
    factory = get_session_factory(resolved)
    with factory() as session:
        has_runs = session.scalar(select(Run.id).limit(1)) is not None
        has_settings = session.scalar(select(Setting.key).limit(1)) is not None
        if has_runs or has_settings:
            return False

        src = sqlite3.connect(str(legacy_path))
        src.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "runs" not in tables and "settings" not in tables:
                return False

            default_project = session.scalar(
                select(Project).where(Project.is_default.is_(True)).limit(1)
            )
            if default_project is None:
                now_ts = utcnow()
                default_project = Project(
                    id="default",
                    name="Default Project",
                    slug="default",
                    description="Default project for runs",
                    is_default=True,
                    created_at=now_ts,
                    updated_at=now_ts,
                )
                session.add(default_project)
                session.flush()

            if "settings" in tables:
                for row in src.execute("SELECT key, value FROM settings"):
                    session.merge(Setting(key=row["key"], value=row["value"]))

            if "runs" in tables:
                for row in src.execute("SELECT * FROM runs"):
                    session.add(
                        Run(
                            id=row["id"],
                            project_id=default_project.id,
                            source=row["source"],
                            title=row["title"],
                            status=row["status"],
                            current_stage=row["current_stage"],
                            error=row["error"],
                            options=row["options"],
                            claimed_by=row["claimed_by"],
                            created_at=_parse_dt(row["created_at"]) or utcnow(),
                            updated_at=_parse_dt(row["updated_at"]) or utcnow(),
                        )
                    )
                session.flush()

            if "stages" in tables:
                for row in src.execute("SELECT * FROM stages"):
                    session.add(
                        Stage(
                            run_id=row["run_id"],
                            name=row["name"],
                            status=row["status"],
                            error=row["error"],
                            started_at=_parse_dt(row["started_at"]),
                            finished_at=_parse_dt(row["finished_at"]),
                        )
                    )

            if "clips" in tables:
                for row in src.execute("SELECT * FROM clips"):
                    session.add(
                        Clip(
                            id=row["id"],
                            run_id=row["run_id"],
                            rank=row["rank"],
                            start_seconds=row["start_seconds"],
                            end_seconds=row["end_seconds"],
                            duration_seconds=row["duration_seconds"],
                            title=row["title"],
                            post_title=row["post_title"],
                            caption=row["caption"],
                            hashtags=row["hashtags"],
                            rationale=row["rationale"],
                            score=row["score"],
                            transcript=row["transcript"],
                            file_path=row["file_path"],
                            width=row["width"],
                            height=row["height"],
                            status=row["status"],
                            error=row["error"],
                            created_at=_parse_dt(row["created_at"]) or utcnow(),
                        )
                    )
                session.flush()

            if "posts" in tables:
                for row in src.execute("SELECT * FROM posts"):
                    session.add(
                        Post(
                            id=row["id"],
                            clip_id=row["clip_id"],
                            channel_id=row["channel_id"],
                            channel_name=row["channel_name"],
                            service=row["service"],
                            mode=row["mode"],
                            scheduled_at=row["scheduled_at"],
                            status=row["status"],
                            buffer_post_id=row["buffer_post_id"],
                            media_url=row["media_url"],
                            error=row["error"],
                            created_at=_parse_dt(row["created_at"]) or utcnow(),
                        )
                    )

            session.commit()
            logger.info("Imported legacy SQLite data from %s into PostgreSQL", legacy_path)
            return True
        finally:
            src.close()


def dispose_engines() -> None:
    """Dispose cached engines (useful in tests)."""
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
        _session_factories.clear()
        _migrated_urls.clear()

