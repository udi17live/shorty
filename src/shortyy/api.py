"""HTTP API and web UI."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from shortyy import __version__, db, pipeline
from shortyy.config import (
    PACKAGE_DIR,
    SETTINGS,
    get_setting,
    load_dotenv_if_present,
    mask,
    uploads_dir,
)
from shortyy.database import ensure_schema, migrate_legacy_sqlite_if_needed
from shortyy.doctor import checks
from shortyy.platforms import PlatformConnectorFactory, PlatformError
from shortyy.publish import BufferClient, PublishError, PublishMode, publish_clip
from shortyy.security import generate_random_token
from shortyy.services import channels as channel_service
from shortyy.services import projects as project_service
from shortyy.services.projects import ProjectError
from shortyy.worker import Worker

WEB_DIR = PACKAGE_DIR / "web"
OAUTH_BINDING_COOKIE = "shorty_oauth_binding"
SAFE_OAUTH_ERROR_CODES = {
    "cancelled",
    "state_missing",
    "state_mismatch",
    "state_reused",
    "state_expired",
    "unauthorized",
    "invalid_project",
    "oauth_denied",
    "invalid_code",
    "exchange_failed",
    "discovery_failed",
    "no_channel",
    "provider_unavailable",
    "not_configured",
    "server_error",
    "unsupported_platform",
}


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)


class CompleteChannelSelectionRequest(BaseModel):
    selection_id: str = Field(..., min_length=1, max_length=64)
    external_channel_ids: list[str] = Field(..., min_length=1, max_length=50)


class CreateRuns(BaseModel):
    sources: list[str] = Field(..., min_length=1, max_length=50)
    options: pipeline.ClipOptions = pipeline.ClipOptions()
    project_id: str | None = None


class RetryRun(BaseModel):
    from_stage: str | None = None


class UpdateSettings(BaseModel):
    values: dict[str, str | None]


class TestConnectionRequest(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class PublishRequest(BaseModel):
    channel_ids: list[str] = Field(..., min_length=1)
    mode: PublishMode = "queue"
    scheduled_at: datetime | None = None
    text: str | None = None
    title: str | None = None


def create_app(start_worker: bool = True) -> FastAPI:
    load_dotenv_if_present()
    worker = Worker() if start_worker else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_schema()
        migrate_legacy_sqlite_if_needed()
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="Shortyy", version=__version__, lifespan=lifespan)

    # ── health & settings ────────────────────────────────────────────────────

    @app.get("/api/health")
    def health() -> dict:
        return {
            "version": __version__,
            "checks": checks(),
            "queue": db.queue_counts(),
            "worker": bool(worker),
        }

    @app.get("/api/settings")
    def get_settings() -> list[dict]:
        result = []
        for key, spec in SETTINGS.items():
            stored = db.get_setting(key)
            value = get_setting(key)
            has_env = bool(
                os.environ.get(spec.env, "").strip()
                or any(os.environ.get(alt, "").strip() for alt in spec.fallback_envs)
            )
            source = "app" if (stored and stored.strip()) else "env" if has_env else "default"
            result.append(
                {
                    "key": key,
                    "value": mask(value) if spec.secret else value,
                    "is_set": bool(value),
                    "secret": spec.secret,
                    "source": source,
                    "env": spec.env,
                    "description": spec.description,
                }
            )
        return result

    @app.put("/api/settings")
    def put_settings(body: UpdateSettings) -> list[dict]:
        for key, value in body.values.items():
            if key not in SETTINGS:
                raise HTTPException(400, f"Unknown setting: {key}")
            if SETTINGS[key].secret and value and "••••" in value:
                continue  # unchanged masked value sent back by the UI
            db.set_setting(key, value.strip() if value else None)
        return get_settings()

    @app.get("/api/providers")
    def get_providers() -> list[dict]:
        from shortyy.providers.factory import LLMProviderFactory

        names = {
            "deepseek": "DeepSeek",
            "openrouter": "OpenRouter",
            "ollama": "Ollama",
        }
        return [
            {"id": p, "name": names.get(p, p.capitalize())}
            for p in LLMProviderFactory.registered_providers()
        ]

    @app.post("/api/settings/test-connection")
    @app.post("/api/test-connection")
    def test_connection_endpoint(body: TestConnectionRequest | None = None) -> dict:
        from shortyy.llm import test_connection

        req = body or TestConnectionRequest()
        key = req.api_key
        if key and "••••" in key:
            key = None
        try:
            return test_connection(
                provider=req.provider,
                model=req.model,
                api_key=key,
                base_url=req.base_url,
            )
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/models")
    def models(provider: str | None = None) -> list[dict]:
        from shortyy.llm import list_models

        try:
            return list_models(provider=provider)
        except Exception as exc:
            raise HTTPException(502, f"Could not load models: {exc}") from exc

    # ── projects & connected channels ────────────────────────────────────────

    @app.get("/api/platforms")
    def list_platforms() -> list[dict]:
        return PlatformConnectorFactory.list_platforms()

    @app.get("/api/projects")
    def list_projects() -> list[dict]:
        return project_service.list_projects()

    @app.post("/api/projects", status_code=201)
    def create_project(body: CreateProjectRequest) -> dict:
        try:
            return project_service.create_project(body.name, body.description)
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        try:
            return project_service.get_project(project_id)
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, body: UpdateProjectRequest) -> dict:
        try:
            return project_service.update_project(
                project_id, name=body.name, description=body.description
            )
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str) -> dict:
        try:
            project_service.delete_project(project_id)
            return {"deleted": project_id}
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.get("/api/projects/{project_id}/runs")
    def list_project_runs(project_id: str) -> list[dict]:
        try:
            project_service.get_project(project_id)
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        return db.list_runs(project_id=project_id)

    @app.post("/api/projects/{project_id}/runs")
    def create_project_runs(project_id: str, body: CreateRuns) -> list[dict]:
        try:
            project_service.get_project(project_id)
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        runs = [
            db.create_run(source.strip(), body.options.model_dump(), project_id=project_id)
            for source in body.sources
            if source.strip()
        ]
        if worker:
            worker.wake()
        return runs

    @app.get("/api/projects/{project_id}/channels")
    def list_project_channels(project_id: str) -> list[dict]:
        try:
            return channel_service.list_project_channels(project_id)
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.post("/api/projects/{project_id}/channels/connect/{platform}")
    def connect_project_channel(
        project_id: str, platform: str, request: Request, response: Response
    ) -> dict[str, str]:
        binding_secret = generate_random_token(32)
        try:
            result = channel_service.initiate_oauth(project_id, platform, binding_secret)
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except PlatformError as exc:
            status = 503 if exc.code == "not_configured" else 400
            raise HTTPException(status, str(exc)) from exc
        response.set_cookie(
            key=OAUTH_BINDING_COOKIE,
            value=binding_secret,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=900,
            path="/",
        )
        return result

    @app.get("/api/oauth/{platform}/callback")
    def oauth_callback(
        platform: str,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        shorty_oauth_binding: str | None = Cookie(default=None, alias=OAUTH_BINDING_COOKIE),
    ) -> RedirectResponse:
        from urllib.parse import urlencode

        result = channel_service.handle_oauth_callback(
            platform,
            code=code,
            state=state,
            error=error,
            binding_secret=shorty_oauth_binding,
        )
        # Strictly internal relative redirect path — never accept arbitrary redirect targets.
        base_path = (
            f"/projects/{result.project_id}/channels" if result.project_id else "/projects"
        )
        params: dict[str, str] = {
            "oauth_status": result.outcome,
            "platform": result.platform,
        }
        if result.outcome == "connected" and result.channel:
            params["channel"] = str(result.channel["id"])
        elif result.outcome == "select" and result.selection_id:
            params["selection"] = result.selection_id
        elif result.outcome == "error":
            safe_code = (
                result.error_code
                if result.error_code in SAFE_OAUTH_ERROR_CODES
                else "exchange_failed"
            )
            params["reason"] = safe_code

        return RedirectResponse(url=f"{base_path}?{urlencode(params)}", status_code=302)

    @app.get("/api/projects/{project_id}/channels/connect/{platform}/pending/{selection_id}")
    def get_pending_channel_selection(
        project_id: str,
        platform: str,
        selection_id: str,
        shorty_oauth_binding: str | None = Cookie(default=None, alias=OAUTH_BINDING_COOKIE),
    ) -> dict[str, Any]:
        try:
            return channel_service.get_pending_selection(
                project_id, platform, selection_id, shorty_oauth_binding
            )
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.post("/api/projects/{project_id}/channels/connect/{platform}/complete")
    def complete_channel_selection(
        project_id: str,
        platform: str,
        body: CompleteChannelSelectionRequest,
        shorty_oauth_binding: str | None = Cookie(default=None, alias=OAUTH_BINDING_COOKIE),
    ) -> list[dict[str, Any]]:
        try:
            return channel_service.complete_pending_selection(
                project_id,
                platform,
                body.selection_id,
                body.external_channel_ids,
                shorty_oauth_binding,
            )
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.post("/api/projects/{project_id}/channels/{channel_id}/disconnect")
    def disconnect_project_channel(project_id: str, channel_id: str) -> dict[str, Any]:
        try:
            return channel_service.disconnect_channel(project_id, channel_id, revoke=False)
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    @app.delete("/api/projects/{project_id}/channels/{channel_id}")
    def remove_project_channel(project_id: str, channel_id: str) -> dict[str, str]:
        try:
            channel_service.remove_channel(project_id, channel_id)
            return {"deleted": channel_id}
        except ProjectError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    # ── runs ─────────────────────────────────────────────────────────────────

    @app.post("/api/uploads")
    def upload(file: UploadFile) -> dict:
        name = Path(file.filename or "upload.mp4").name
        target = uploads_dir() / f"{db.new_id()}-{name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh, length=1024 * 1024)
        return {"source": str(target), "name": name}

    @app.post("/api/runs")
    def create_runs(body: CreateRuns) -> list[dict]:
        if body.project_id:
            try:
                project_service.get_project(body.project_id)
            except ProjectError as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
        runs = [
            db.create_run(source.strip(), body.options.model_dump(), project_id=body.project_id)
            for source in body.sources
            if source.strip()
        ]
        if worker:
            worker.wake()
        return runs

    @app.get("/api/runs")
    def list_runs(project_id: str | None = None) -> list[dict]:
        if project_id is not None:
            try:
                project_service.get_project(project_id)
            except ProjectError as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
        return db.list_runs(project_id=project_id)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        return run_detail(run_id)

    @app.post("/api/runs/{run_id}/retry")
    def retry_run(run_id: str, body: RetryRun | None = None) -> dict:
        run = _run_or_404(run_id)
        if run["status"] in {"queued", "running"}:
            raise HTTPException(409, "Run is already queued or running")
        from_stage = body.from_stage if body else None
        if from_stage and from_stage not in pipeline.STAGE_NAMES:
            raise HTTPException(400, f"Unknown stage: {from_stage}")
        pipeline.retry(run_id, from_stage)
        if worker:
            worker.wake()
        return run_detail(run_id)

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict:
        run = _run_or_404(run_id)
        if run["status"] == "running":
            raise HTTPException(409, "Wait for the run to finish before deleting it")
        pipeline.delete(run_id)
        return {"deleted": run_id}

    @app.get("/api/runs/{run_id}/download")
    def download_run(run_id: str) -> FileResponse:
        run = _run_or_404(run_id)
        clips = [c for c in db.list_clips(run_id) if c["status"] == "ready" and c["file_path"]]
        if not clips:
            raise HTTPException(404, "No clips to download yet")
        fd, tmp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            for clip in clips:
                zf.write(clip["file_path"], Path(clip["file_path"]).name)
            zf.writestr(
                "clips.json", json.dumps([_clip_public(c) for c in clips], indent=2, ensure_ascii=False)
            )
        name = f"shortyy-{_safe(run['title'] or run_id)}.zip"
        return FileResponse(
            tmp, filename=name, media_type="application/zip", background=BackgroundTask(os.unlink, tmp)
        )

    # ── clips & publishing ───────────────────────────────────────────────────

    @app.get("/api/clips/{clip_id}/video")
    def clip_video(clip_id: str, download: bool = False) -> FileResponse:
        clip = db.get_clip(clip_id)
        if not clip or not clip["file_path"] or not Path(clip["file_path"]).exists():
            raise HTTPException(404, "Clip file not found")
        _run_or_404(clip["run_id"])
        path = Path(clip["file_path"])
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=path.name if download else None,
            content_disposition_type="attachment" if download else "inline",
        )

    @app.get("/api/clips/{clip_id}/poster")
    def clip_poster(clip_id: str) -> FileResponse:
        from shortyy.render import make_poster, poster_path

        clip = db.get_clip(clip_id)
        if not clip or not clip["file_path"] or not Path(clip["file_path"]).exists():
            raise HTTPException(404, "Clip file not found")
        _run_or_404(clip["run_id"])
        poster = poster_path(Path(clip["file_path"]))
        if not poster.exists():
            make_poster(Path(clip["file_path"]), 1.0)
        return FileResponse(poster, media_type="image/jpeg")

    @app.get("/api/buffer/channels")
    def buffer_channels() -> list[dict]:
        try:
            return BufferClient().channels()
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/buffer/organizations")
    def buffer_organizations() -> list[dict]:
        try:
            return BufferClient().organizations()
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/clips/{clip_id}/publish")
    def publish(clip_id: str, body: PublishRequest) -> list[dict]:
        try:
            return publish_clip(
                clip_id, body.channel_ids, body.mode, body.scheduled_at, body.text, body.title
            )
        except PublishError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ── web UI ───────────────────────────────────────────────────────────────

    if (WEB_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (WEB_DIR / path).resolve()
            if path and candidate.is_file() and WEB_DIR.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(WEB_DIR / "index.html")

    return app


def run_detail(run_id: str) -> dict:
    run = _run_or_404(run_id)
    stage_rows = {s["name"]: s for s in db.list_stages(run_id)}
    stages = [
        {
            "name": name,
            "label": label,
            **{
                k: v
                for k, v in stage_rows.get(name, {}).items()
                if k in {"status", "error", "started_at", "finished_at"}
            },
        }
        for name, label, _ in pipeline.STAGES
    ]
    for stage in stages:
        stage.setdefault("status", "pending")
    source_file = pipeline.run_dir(run_id) / "work" / "download.json"
    source_duration = None
    if source_file.exists():
        source_duration = json.loads(source_file.read_text(encoding="utf-8")).get("duration_seconds")
    return {
        **run,
        "source_duration": source_duration,
        "stages": stages,
        "clips": [_clip_public(c) for c in db.list_clips(run_id)],
        "posts": db.list_posts(run_id=run_id),
    }


def _clip_public(clip: dict) -> dict:
    data = {k: v for k, v in clip.items() if k != "file_path"}
    data["filename"] = Path(clip["file_path"]).name if clip.get("file_path") else None
    data["video_url"] = f"/api/clips/{clip['id']}/video"
    data["poster_url"] = f"/api/clips/{clip['id']}/poster"
    data["download_url"] = f"/api/clips/{clip['id']}/video?download=true"
    return data


def _run_or_404(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    try:
        project_service.get_project(run["project_id"])
    except ProjectError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return run


def _safe(text: str) -> str:
    from shortyy.render import slugify

    return slugify(text)
