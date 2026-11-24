"""Database access layer backed by SQLAlchemy (PostgreSQL in production, SQLite fallback)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update

from clipyyy.database import session_scope
from clipyyy.models import Clip, Post, Project, Run, Setting, Stage, utcnow


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _dt_to_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _run_dict(run: Run, clip_count: int | None = None, project_name: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": run.id,
        "project_id": run.project_id,
        "source": run.source,
        "title": run.title,
        "status": run.status,
        "current_stage": run.current_stage,
        "error": run.error,
        "options": json.loads(run.options) if run.options else None,
        "claimed_by": run.claimed_by,
        "created_at": _dt_to_iso(run.created_at),
        "updated_at": _dt_to_iso(run.updated_at),
    }
    if clip_count is not None:
        data["clip_count"] = clip_count
    if project_name is not None:
        data["project_name"] = project_name
    return data


def _stage_dict(stage: Stage) -> dict[str, Any]:
    return {
        "run_id": stage.run_id,
        "name": stage.name,
        "status": stage.status,
        "error": stage.error,
        "started_at": _dt_to_iso(stage.started_at),
        "finished_at": _dt_to_iso(stage.finished_at),
    }


def _clip_dict(clip: Clip) -> dict[str, Any]:
    return {
        "id": clip.id,
        "run_id": clip.run_id,
        "rank": clip.rank,
        "start_seconds": clip.start_seconds,
        "end_seconds": clip.end_seconds,
        "duration_seconds": clip.duration_seconds,
        "title": clip.title,
        "post_title": clip.post_title,
        "caption": clip.caption,
        "hashtags": json.loads(clip.hashtags) if clip.hashtags else [],
        "rationale": clip.rationale,
        "score": clip.score,
        "transcript": clip.transcript,
        "file_path": clip.file_path,
        "width": clip.width,
        "height": clip.height,
        "status": clip.status,
        "error": clip.error,
        "created_at": _dt_to_iso(clip.created_at),
    }


def _post_dict(post: Post) -> dict[str, Any]:
    return {
        "id": post.id,
        "clip_id": post.clip_id,
        "channel_id": post.channel_id,
        "channel_name": post.channel_name,
        "service": post.service,
        "mode": post.mode,
        "scheduled_at": post.scheduled_at,
        "status": post.status,
        "buffer_post_id": post.buffer_post_id,
        "media_url": post.media_url,
        "error": post.error,
        "created_at": _dt_to_iso(post.created_at),
    }


def _ensure_default_project_id(session: Any) -> str:
    project = session.scalar(select(Project).where(Project.is_default.is_(True)).limit(1))
    if project is None:
        project = session.scalar(select(Project).order_by(Project.created_at.asc()).limit(1))
    if project is None:
        ts = utcnow()
        project = Project(
            id="default",
            name="Default Project",
            slug="default",
            description="Default project for clips and connected channels",
            is_default=True,
            created_at=ts,
            updated_at=ts,
        )
        session.add(project)
        session.flush()
    return project.id


# ── runs ─────────────────────────────────────────────────────────────────────


def create_run(
    source: str,
    options: dict[str, Any],
    status: str = "queued",
    project_id: str | None = None,
) -> dict[str, Any]:
    run_id = new_id()
    ts = utcnow()
    with session_scope() as session:
        resolved_project_id = project_id or _ensure_default_project_id(session)
        run = Run(
            id=run_id,
            project_id=resolved_project_id,
            source=source,
            status=status,
            options=json.dumps(options),
            claimed_by=os.getpid() if status == "running" else None,
            created_at=ts,
            updated_at=ts,
        )
        session.add(run)
        session.flush()
        return _run_dict(run)


def get_run(run_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.execute(
            select(Run, Project.name).join(Project, Project.id == Run.project_id).where(Run.id == run_id)
        ).first()
        if row is None:
            return None
        run, project_name = row
        return _run_dict(run, project_name=project_name)


def list_runs(
    limit: int = 200,
    project_id: str | None = None,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        clip_count_sq = (
            select(func.count(Clip.id))
            .where(Clip.run_id == Run.id, Clip.status == "ready")
            .correlate(Run)
            .scalar_subquery()
        )
        stmt = (
            select(Run, clip_count_sq.label("clip_count"), Project.name.label("project_name"))
            .join(Project, Project.id == Run.project_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        )
        if owner_id is not None:
            stmt = stmt.where((Project.owner_id == owner_id) | (Project.owner_id.is_(None)))
        else:
            stmt = stmt.where(Project.owner_id.is_(None))
        if project_id:
            stmt = stmt.where(Run.project_id == project_id)
        rows = session.execute(stmt).all()
        return [_run_dict(r, clip_count=int(c or 0), project_name=pname) for r, c, pname in rows]


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    values = dict(fields)
    if "options" in values and not isinstance(values["options"], str):
        values["options"] = json.dumps(values["options"])
    values["updated_at"] = utcnow()
    with session_scope() as session:
        session.execute(update(Run).where(Run.id == run_id).values(**values))


def delete_run(run_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(Run).where(Run.id == run_id))


def claim_next_run() -> dict[str, Any] | None:
    """Atomically move the oldest queued run to ``running``."""
    with session_scope() as session:
        stmt = select(Run).where(Run.status == "queued").order_by(Run.created_at.asc()).limit(1)
        if session.bind and session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        run = session.scalar(stmt)
        if run is None:
            return None
        run.status = "running"
        run.error = None
        run.claimed_by = os.getpid()
        run.updated_at = utcnow()
        session.flush()
        return _run_dict(run)


def queue_counts() -> dict[str, int]:
    with session_scope() as session:
        rows = session.execute(
            select(Run.status, func.count(Run.id))
            .where(Run.status.in_(["queued", "running"]))
            .group_by(Run.status)
        ).all()
    counts = {"queued": 0, "running": 0}
    counts.update({status: int(n) for status, n in rows})
    return counts


def requeue_interrupted_runs() -> None:
    """Runs left ``running`` by a process that no longer exists go back to the queue and resume.

    Runs owned by a live process (for example a foreground ``clipyyy clip``) are left alone.
    """
    with session_scope() as session:
        running = session.scalars(select(Run).where(Run.status == "running")).all()
        for run in running:
            if run.claimed_by and _alive(run.claimed_by):
                continue
            run.status = "queued"
            run.claimed_by = None
            run.updated_at = utcnow()
            session.execute(
                update(Stage)
                .where(Stage.run_id == run.id, Stage.status == "running")
                .values(status="pending")
            )


def _alive(pid: int) -> bool:
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ── stages ───────────────────────────────────────────────────────────────────


def set_stage(run_id: str, name: str, status: str, error: str | None = None) -> None:
    ts = utcnow()
    with session_scope() as session:
        stage = session.get(Stage, (run_id, name))
        if stage is None:
            stage = Stage(
                run_id=run_id,
                name=name,
                status=status,
                error=error,
                started_at=ts if status == "running" else None,
                finished_at=ts if status in {"done", "failed", "skipped"} else None,
            )
            session.add(stage)
        else:
            stage.status = status
            stage.error = error
            if status == "running":
                stage.started_at = ts
            stage.finished_at = ts if status in {"done", "failed", "skipped"} else None


def list_stages(run_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(select(Stage).where(Stage.run_id == run_id)).all()
        return [_stage_dict(s) for s in rows]


# ── clips ────────────────────────────────────────────────────────────────────


def replace_clips(run_id: str, clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ts = utcnow()
    with session_scope() as session:
        session.execute(delete(Clip).where(Clip.run_id == run_id))
        for clip_data in clips:
            payload = dict(clip_data)
            hashtags = payload.get("hashtags") or []
            if not isinstance(hashtags, str):
                hashtags = json.dumps(hashtags)
            clip = Clip(
                id=new_id(),
                run_id=run_id,
                rank=payload["rank"],
                start_seconds=payload["start_seconds"],
                end_seconds=payload["end_seconds"],
                duration_seconds=payload.get("duration_seconds"),
                title=payload["title"],
                post_title=payload["post_title"],
                caption=payload["caption"],
                hashtags=hashtags,
                rationale=payload["rationale"],
                score=payload.get("score"),
                transcript=payload["transcript"],
                file_path=payload.get("file_path"),
                width=payload.get("width"),
                height=payload.get("height"),
                status=payload["status"],
                error=payload.get("error"),
                created_at=ts,
            )
            session.add(clip)
    return list_clips(run_id)


def list_clips(run_id: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(select(Clip).where(Clip.run_id == run_id).order_by(Clip.rank)).all()
        return [_clip_dict(c) for c in rows]


def get_clip(clip_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        return _clip_dict(clip) if clip else None


def update_clip(clip_id: str, **fields: Any) -> None:
    if not fields:
        return
    values = dict(fields)
    if "hashtags" in values and not isinstance(values["hashtags"], str):
        values["hashtags"] = json.dumps(values["hashtags"])
    with session_scope() as session:
        session.execute(update(Clip).where(Clip.id == clip_id).values(**values))


# ── posts ────────────────────────────────────────────────────────────────────


def create_post(**fields: Any) -> dict[str, Any]:
    post = Post(
        id=new_id(),
        created_at=utcnow(),
        clip_id=fields["clip_id"],
        channel_id=fields["channel_id"],
        channel_name=fields.get("channel_name"),
        service=fields.get("service"),
        mode=fields["mode"],
        scheduled_at=fields.get("scheduled_at"),
        status=fields["status"],
        buffer_post_id=fields.get("buffer_post_id"),
        media_url=fields.get("media_url"),
        error=fields.get("error"),
    )
    with session_scope() as session:
        session.add(post)
        session.flush()
        return _post_dict(post)


def list_posts(clip_id: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = select(Post).join(Clip, Clip.id == Post.clip_id)
        if clip_id:
            stmt = stmt.where(Post.clip_id == clip_id)
        elif run_id:
            stmt = stmt.where(Clip.run_id == run_id)
        rows = session.scalars(stmt.order_by(Post.created_at.desc())).all()
        return [_post_dict(p) for p in rows]


# ── settings ─────────────────────────────────────────────────────────────────


def get_setting(key: str) -> str | None:
    with session_scope() as session:
        setting = session.get(Setting, key)
        return setting.value if setting else None


def set_setting(key: str, value: str | None) -> None:
    with session_scope() as session:
        if value:
            existing = session.get(Setting, key)
            if existing:
                existing.value = value
            else:
                session.add(Setting(key=key, value=value))
        else:
            session.execute(delete(Setting).where(Setting.key == key))
