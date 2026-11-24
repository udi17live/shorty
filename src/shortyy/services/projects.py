"""Project service layer."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select

from shortyy import db
from shortyy.database import session_scope
from shortyy.models import ConnectedChannel, Project, Run, utcnow


class ProjectError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProjectNotFoundError(ProjectError):
    def __init__(self, message: str = "Project not found") -> None:
        super().__init__(message, status_code=404)


class ProjectAccessError(ProjectError):
    def __init__(self, message: str = "You do not have access to this project") -> None:
        super().__init__(message, status_code=403)


def slugify_project(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "project"


def _unique_slug(session: Any, base_slug: str, exclude_id: str | None = None) -> str:
    candidate = base_slug
    idx = 2
    while True:
        stmt = select(Project.id).where(Project.slug == candidate)
        if exclude_id:
            stmt = stmt.where(Project.id != exclude_id)
        if session.scalar(stmt) is None:
            return candidate
        candidate = f"{base_slug}-{idx}"
        idx += 1


def _project_dict(
    project: Project,
    *,
    run_count: int = 0,
    channel_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "owner_id": project.owner_id,
        "is_default": bool(project.is_default),
        "run_count": run_count,
        "channel_count": channel_count,
        "created_at": db._dt_to_iso(project.created_at),
        "updated_at": db._dt_to_iso(project.updated_at),
    }


def require_project(session: Any, project_id: str, owner_id: str | None = None) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError()
    if project.owner_id is not None and project.owner_id != owner_id:
        raise ProjectAccessError()
    return project


def list_projects(owner_id: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        run_count_sq = (
            select(func.count(Run.id))
            .where(Run.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )
        channel_count_sq = (
            select(func.count(ConnectedChannel.id))
            .where(
                ConnectedChannel.project_id == Project.id,
                ConnectedChannel.status != "disconnected",
            )
            .correlate(Project)
            .scalar_subquery()
        )
        stmt = (
            select(
                Project,
                run_count_sq.label("run_count"),
                channel_count_sq.label("channel_count"),
            )
            .order_by(Project.is_default.desc(), Project.created_at.asc())
        )
        if owner_id is not None:
            stmt = stmt.where((Project.owner_id == owner_id) | (Project.owner_id.is_(None)))
        else:
            stmt = stmt.where(Project.owner_id.is_(None))
        rows = session.execute(stmt).all()
        return [
            _project_dict(p, run_count=int(rc or 0), channel_count=int(cc or 0))
            for p, rc, cc in rows
        ]


def get_project(project_id: str, owner_id: str | None = None) -> dict[str, Any]:
    with session_scope() as session:
        project = require_project(session, project_id, owner_id=owner_id)
        run_count = session.scalar(select(func.count(Run.id)).where(Run.project_id == project.id)) or 0
        channel_count = (
            session.scalar(
                select(func.count(ConnectedChannel.id)).where(
                    ConnectedChannel.project_id == project.id,
                    ConnectedChannel.status != "disconnected",
                )
            )
            or 0
        )
        return _project_dict(project, run_count=int(run_count), channel_count=int(channel_count))


def get_default_project(owner_id: str | None = None) -> dict[str, Any]:
    with session_scope() as session:
        project = session.scalar(
            select(Project)
            .where(Project.is_default.is_(True))
            .order_by(Project.created_at.asc())
            .limit(1)
        )
        if project is None:
            project = session.scalar(select(Project).order_by(Project.created_at.asc()).limit(1))
        if project is None:
            ts = utcnow()
            project = Project(
                id="default",
                name="Default Project",
                slug="default",
                description="Default project for clips and connected channels",
                owner_id=owner_id,
                is_default=True,
                created_at=ts,
                updated_at=ts,
            )
            session.add(project)
            session.flush()
        return _project_dict(project)


def create_project(
    name: str,
    description: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    cleaned = name.strip()
    if not cleaned:
        raise ProjectError("Project name is required", status_code=400)
    with session_scope() as session:
        ts = utcnow()
        slug = _unique_slug(session, slugify_project(cleaned))
        project = Project(
            id=db.new_id(),
            name=cleaned,
            slug=slug,
            description=description.strip() if description and description.strip() else None,
            owner_id=owner_id,
            is_default=False,
            created_at=ts,
            updated_at=ts,
        )
        session.add(project)
        session.flush()
        return _project_dict(project)


def update_project(
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    with session_scope() as session:
        project = require_project(session, project_id, owner_id=owner_id)
        if name is not None:
            cleaned = name.strip()
            if not cleaned:
                raise ProjectError("Project name cannot be empty", status_code=400)
            project.name = cleaned
            project.slug = _unique_slug(session, slugify_project(cleaned), exclude_id=project.id)
        if description is not None:
            project.description = description.strip() or None
        project.updated_at = utcnow()
        session.flush()
        run_count = session.scalar(select(func.count(Run.id)).where(Run.project_id == project.id)) or 0
        channel_count = (
            session.scalar(
                select(func.count(ConnectedChannel.id)).where(
                    ConnectedChannel.project_id == project.id,
                    ConnectedChannel.status != "disconnected",
                )
            )
            or 0
        )
        return _project_dict(project, run_count=int(run_count), channel_count=int(channel_count))


def delete_project(project_id: str, owner_id: str | None = None) -> None:
    with session_scope() as session:
        project = require_project(session, project_id, owner_id=owner_id)
        total = session.scalar(select(func.count(Project.id))) or 0
        if total <= 1:
            raise ProjectError("Cannot delete the last remaining project", status_code=409)
        active_runs = (
            session.scalar(
                select(func.count(Run.id)).where(
                    Run.project_id == project.id,
                    Run.status.in_(["queued", "running"]),
                )
            )
            or 0
        )
        if active_runs > 0:
            raise ProjectError(
                "Wait for active or queued runs in this project to finish before deleting it",
                status_code=409,
            )
        was_default = project.is_default
        session.delete(project)
        session.flush()
        if was_default:
            next_default = session.scalar(select(Project).order_by(Project.created_at.asc()).limit(1))
            if next_default:
                next_default.is_default = True

