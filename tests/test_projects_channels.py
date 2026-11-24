from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from clipyyy import db
from clipyyy.api import create_app
from clipyyy.database import dispose_engines, run_migrations, session_scope
from clipyyy.models import ConnectedChannel, OAuthCredential, OAuthState, utcnow
from clipyyy.platforms import (
    PlatformConnectorFactory,
    ReauthorizationRequiredError,
    YouTubeConnector,
)
from clipyyy.security import decrypt_secret, hash_token
from clipyyy.services import channels as channel_service
from clipyyy.services import projects as project_service
from clipyyy.services.projects import ProjectAccessError


@pytest.fixture
def oauth_env(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", key)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret-value")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/oauth/youtube/callback")
    return key


@pytest.fixture
def client(oauth_env):
    with TestClient(create_app(start_worker=False)) as c:
        yield c


def _mock_youtube_connector(
    *,
    channels_payload: dict | None = None,
    token_status: int = 200,
    token_payload: dict | None = None,
    channels_status: int = 200,
    refresh_status: int = 200,
    refresh_payload: dict | None = None,
) -> YouTubeConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://oauth2.googleapis.com/token"):
            body = request.content.decode("utf-8")
            if "grant_type=refresh_token" in body:
                if refresh_status >= 400:
                    return httpx.Response(refresh_status, json=refresh_payload or {"error": "invalid_grant"})
                return httpx.Response(
                    200,
                    json=refresh_payload
                    or {
                        "access_token": "ya29.refreshed-access-token",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                        "scope": "https://www.googleapis.com/auth/youtube.readonly",
                    },
                )
            if token_status >= 400:
                return httpx.Response(token_status, json=token_payload or {"error": "invalid_grant"})
            return httpx.Response(
                200,
                json=token_payload
                or {
                    "access_token": "ya29.initial-access-token",
                    "refresh_token": "1//initial-refresh-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "https://www.googleapis.com/auth/youtube.readonly",
                },
            )
        if url.startswith("https://www.googleapis.com/youtube/v3/channels"):
            if channels_status >= 400:
                return httpx.Response(channels_status, json={"error": {"status": "PERMISSION_DENIED"}})
            return httpx.Response(
                200,
                json=channels_payload
                if channels_payload is not None
                else {
                    "items": [
                        {
                            "id": "UC_GTA6_SHORTS",
                            "snippet": {
                                "title": "GTA 6 Shorts",
                                "customUrl": "@gta6shorts",
                                "description": "Best GTA 6 clips",
                                "thumbnails": {
                                    "high": {"url": "https://yt3.ggpht.com/avatar-gta6.jpg"}
                                },
                            },
                        }
                    ]
                },
            )
        if url.startswith("https://oauth2.googleapis.com/revoke"):
            return httpx.Response(200, json={})
        raise AssertionError(f"Unexpected HTTP call: {url}")

    return YouTubeConnector(transport=httpx.MockTransport(handler))


# ── Projects ─────────────────────────────────────────────────────────────────


def test_project_crud_and_run_association(client):
    # Default project is created automatically
    projects = client.get("/api/projects").json()
    assert len(projects) == 1
    assert projects[0]["is_default"] is True

    # Create project
    created = client.post(
        "/api/projects",
        json={"name": "GTA 6", "description": "Grand Theft Auto VI channel"},
    )
    assert created.status_code == 201
    p = created.json()
    assert p["name"] == "GTA 6"
    assert p["slug"] == "gta-6"

    # Update project
    updated = client.patch(f"/api/projects/{p['id']}", json={"name": "GTA 6 Official"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "GTA 6 Official"
    assert updated.json()["slug"] == "gta-6-official"

    # Create run scoped to project
    run_res = client.post(
        f"/api/projects/{p['id']}/runs",
        json={"sources": ["https://youtu.be/dQw4w9WgXcQ"], "options": {"clip_count": 3}},
    )
    assert run_res.status_code == 200
    run = run_res.json()[0]
    assert run["project_id"] == p["id"]

    scoped_runs = client.get(f"/api/projects/{p['id']}/runs").json()
    assert [r["id"] for r in scoped_runs] == [run["id"]]

    # Cannot delete project while runs are queued, nor delete the last project
    assert client.delete(f"/api/projects/{p['id']}").status_code == 409
    db.update_run(run["id"], status="completed")
    del_res = client.delete(f"/api/projects/{p['id']}")
    assert del_res.status_code == 200
    assert client.get(f"/api/projects/{p['id']}").status_code == 404
    assert client.delete("/api/projects/default").status_code == 409


def test_project_ownership_isolation():
    p = project_service.create_project("Owner A Project", owner_id="user-a")
    assert project_service.get_project(p["id"], owner_id="user-a")["id"] == p["id"]
    with pytest.raises(ProjectAccessError):
        project_service.get_project(p["id"], owner_id="user-b")
    with pytest.raises(ProjectAccessError):
        channel_service.initiate_oauth(p["id"], "youtube", "secret", owner_id="user-b")


def test_api_project_isolation_and_run_scoping(client):
    proj_a = client.post("/api/projects", json={"name": "GTA 6"}).json()
    proj_b = client.post("/api/projects", json={"name": "GTA RP"}).json()

    run_a = client.post(
        f"/api/projects/{proj_a['id']}/runs",
        json={"sources": ["https://youtu.be/aaa"], "options": {"clip_count": 3}},
    ).json()[0]
    run_b = client.post(
        f"/api/projects/{proj_b['id']}/runs",
        json={"sources": ["https://youtu.be/bbb"], "options": {"clip_count": 3}},
    ).json()[0]

    # Project-scoped endpoints only return runs for that project
    assert [r["id"] for r in client.get(f"/api/projects/{proj_a['id']}/runs").json()] == [run_a["id"]]
    assert [r["id"] for r in client.get(f"/api/projects/{proj_b['id']}/runs").json()] == [run_b["id"]]

    # ALL RUNS returns runs across all accessible projects
    all_ids = {r["id"] for r in client.get("/api/runs").json()}
    assert {run_a["id"], run_b["id"]}.issubset(all_ids)

    # Tampering with project_id (e.g., forged localStorage value) cannot bypass backend ownership checks
    private_proj = project_service.create_project("Private Brand", owner_id="other-user")
    private_run = db.create_run("https://youtu.be/secret", {"clip_count": 3}, project_id=private_proj["id"])

    assert client.get(f"/api/projects/{private_proj['id']}").status_code == 403
    assert client.get(f"/api/projects/{private_proj['id']}/runs").status_code == 403
    assert client.post(
        f"/api/projects/{private_proj['id']}/runs",
        json={"sources": ["https://youtu.be/x"], "options": {"clip_count": 3}},
    ).status_code == 403
    assert client.get(f"/api/projects/{private_proj['id']}/channels").status_code == 403
    assert client.get("/api/runs", params={"project_id": private_proj["id"]}).status_code == 403
    assert client.post(
        "/api/runs",
        json={
            "sources": ["https://youtu.be/x"],
            "options": {"clip_count": 3},
            "project_id": private_proj["id"],
        },
    ).status_code == 403
    assert client.get(f"/api/runs/{private_run['id']}").status_code == 403
    assert private_run["id"] not in {r["id"] for r in client.get("/api/runs").json()}


# ── OAuth Initiation, Security & Callback ────────────────────────────────────


def test_missing_encryption_key_or_google_config_fails_safely(client, monkeypatch):
    monkeypatch.delenv("OAUTH_ENCRYPTION_KEY", raising=False)
    r = client.post("/api/projects/default/channels/connect/youtube")
    assert r.status_code == 503
    assert "OAUTH_ENCRYPTION_KEY" in r.json()["detail"]

    platforms = {p["id"]: p for p in client.get("/api/platforms").json()}
    assert platforms["youtube"]["configured"] is False
    assert platforms["tiktok"]["status"] == "coming_soon"


def _init_state(client: TestClient, project_id: str = "default") -> str:
    res = client.post(f"/api/projects/{project_id}/channels/connect/youtube")
    return parse_qs(urlparse(res.json()["authorization_url"]).query)["state"][0]


def _mock_factory(monkeypatch, connector: YouTubeConnector) -> None:
    monkeypatch.setattr(
        PlatformConnectorFactory,
        "get_connector",
        classmethod(lambda cls, p, **kw: connector),
    )


def test_oauth_connect_single_channel_and_never_exposes_tokens(client, monkeypatch):
    _mock_factory(monkeypatch, _mock_youtube_connector())

    project = client.post("/api/projects", json={"name": "GTA 6"}).json()
    init_res = client.post(f"/api/projects/{project['id']}/channels/connect/youtube")
    assert init_res.status_code == 200
    auth_url = init_res.json()["authorization_url"]

    parsed = urlparse(auth_url)
    qs = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert qs["scope"] == ["https://www.googleapis.com/auth/youtube.readonly"]
    assert "youtube.upload" not in qs["scope"][0]
    assert qs["redirect_uri"] == ["http://localhost:8000/api/oauth/youtube/callback"]
    assert qs["code_challenge_method"] == ["S256"]
    state = qs["state"][0]

    # Simulate Google callback with TestClient holding the HttpOnly CSRF cookie
    cb_res = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "auth-code-123", "state": state},
        follow_redirects=False,
    )
    assert cb_res.status_code == 302
    loc = cb_res.headers["location"]
    assert loc.startswith(f"/projects/{project['id']}/channels?")
    assert "oauth_status=connected" in loc
    assert "access_token" not in loc
    assert "refresh_token" not in loc

    # Channel is persisted and safe metadata is returned without tokens
    channels = client.get(f"/api/projects/{project['id']}/channels").json()
    assert len(channels) == 1
    ch = channels[0]
    assert ch["platform"] == "youtube"
    assert ch["external_channel_id"] == "UC_GTA6_SHORTS"
    assert ch["display_name"] == "GTA 6 Shorts"
    assert ch["handle"] == "@gta6shorts"
    assert ch["avatar_url"] == "https://yt3.ggpht.com/avatar-gta6.jpg"
    assert ch["status"] == "connected"

    serialized = json.dumps(channels)
    for secret in ("ya29.initial-access-token", "1//initial-refresh-token", "test-client-secret-value"):
        assert secret not in serialized
    for key in ("access_token", "refresh_token", "encrypted_access_token", "encrypted_refresh_token"):
        assert key not in ch

    # Verify DB stores encrypted ciphertext, never plaintext
    with session_scope() as session:
        cred = session.scalar(select(OAuthCredential).where(OAuthCredential.connected_channel_id == ch["id"]))
        assert cred is not None
        assert cred.encrypted_access_token != "ya29.initial-access-token"
        assert cred.encrypted_refresh_token != "1//initial-refresh-token"
        assert decrypt_secret(cred.encrypted_access_token) == "ya29.initial-access-token"
        assert decrypt_secret(cred.encrypted_refresh_token) == "1//initial-refresh-token"


def test_oauth_state_security_rejects_missing_mismatch_expired_reused_and_csrf(client, monkeypatch):
    _mock_factory(monkeypatch, _mock_youtube_connector())

    # 1. Missing state
    r1 = client.get("/api/oauth/youtube/callback", params={"code": "abc"}, follow_redirects=False)
    assert r1.status_code == 302 and "reason=state_missing" in r1.headers["location"]

    # 2. Unknown/mismatched state
    r2 = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "abc", "state": "bogus-state"},
        follow_redirects=False,
    )
    assert r2.status_code == 302 and "reason=state_mismatch" in r2.headers["location"]

    # 3. Missing/mismatched CSRF browser binding cookie (victim vs attacker threat model)
    init_res = client.post("/api/projects/default/channels/connect/youtube")
    state = parse_qs(urlparse(init_res.json()["authorization_url"]).query)["state"][0]
    with TestClient(create_app(start_worker=False)) as victim_client:
        # Victim has no cookie from attacker's initiation
        r_csrf = victim_client.get(
            "/api/oauth/youtube/callback",
            params={"code": "attacker-code", "state": state},
            follow_redirects=False,
        )
        assert r_csrf.status_code == 302 and "reason=state_mismatch" in r_csrf.headers["location"]
    assert client.get("/api/projects/default/channels").json() == []

    # 4. State replay (reused state)
    ok_res = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "valid-code", "state": state},
        follow_redirects=False,
    )
    assert "oauth_status=connected" in ok_res.headers["location"]
    replay_res = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "valid-code", "state": state},
        follow_redirects=False,
    )
    assert "reason=state_reused" in replay_res.headers["location"]

    # 5. Expired state
    init_exp = client.post("/api/projects/default/channels/connect/youtube")
    exp_state = parse_qs(urlparse(init_exp.json()["authorization_url"]).query)["state"][0]
    with session_scope() as session:
        row = session.scalar(select(OAuthState).where(OAuthState.state_hash == hash_token(exp_state)))
        row.expires_at = utcnow() - timedelta(minutes=1)
    exp_res = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "valid-code", "state": exp_state},
        follow_redirects=False,
    )
    assert "reason=state_expired" in exp_res.headers["location"]


def test_oauth_redirect_cannot_be_hijacked_via_query_param(client, monkeypatch):
    _mock_factory(monkeypatch, _mock_youtube_connector())
    state = _init_state(client)
    cb = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "c", "state": state, "redirect": "https://evil.example"},
        follow_redirects=False,
    )
    assert cb.headers["location"].startswith("/projects/default/channels?")
    assert "evil.example" not in cb.headers["location"]


def test_oauth_error_scenarios_denial_no_channel_exchange_fail_api_unavailable(client, monkeypatch):
    # OAuth denied
    _mock_factory(monkeypatch, _mock_youtube_connector())
    s1 = _init_state(client)
    r_denied = client.get(
        "/api/oauth/youtube/callback",
        params={"error": "access_denied", "state": s1},
        follow_redirects=False,
    )
    assert "oauth_status=cancelled" in r_denied.headers["location"]

    # No YouTube channel found
    _mock_factory(monkeypatch, _mock_youtube_connector(channels_payload={"items": []}))
    s2 = _init_state(client)
    r_none = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "c", "state": s2},
        follow_redirects=False,
    )
    assert "reason=no_channel" in r_none.headers["location"]

    # Invalid authorization code
    _mock_factory(monkeypatch, _mock_youtube_connector(token_status=400))
    s3 = _init_state(client)
    r_bad = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "bad", "state": s3},
        follow_redirects=False,
    )
    assert "reason=exchange_failed" in r_bad.headers["location"]

    # Google API unavailable
    _mock_factory(monkeypatch, _mock_youtube_connector(channels_status=503))
    s4 = _init_state(client)
    r_503 = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "c", "state": s4},
        follow_redirects=False,
    )
    assert "reason=provider_unavailable" in r_503.headers["location"]


def test_multi_channel_selection_multiple_per_project_and_idempotent_reconnect(client, monkeypatch):
    multi_connector = _mock_youtube_connector(
        channels_payload={
            "items": [
                {"id": "UC_CH_1", "snippet": {"title": "GTA 6 Shorts", "customUrl": "@gta6shorts"}},
                {"id": "UC_CH_2", "snippet": {"title": "GTA 6 Clips", "customUrl": "@gta6clips"}},
            ]
        }
    )
    monkeypatch.setattr(
        PlatformConnectorFactory, "get_connector", classmethod(lambda cls, p, **kw: multi_connector)
    )

    project = client.post("/api/projects", json={"name": "GTA 6"}).json()
    state = parse_qs(
        urlparse(client.post(f"/api/projects/{project['id']}/channels/connect/youtube").json()["authorization_url"]).query
    )["state"][0]

    cb = client.get(
        "/api/oauth/youtube/callback",
        params={"code": "multi", "state": state},
        follow_redirects=False,
    )
    loc = cb.headers["location"]
    assert "oauth_status=select" in loc
    selection_id = parse_qs(urlparse(loc).query)["selection"][0]

    pending = client.get(
        f"/api/projects/{project['id']}/channels/connect/youtube/pending/{selection_id}"
    ).json()
    assert len(pending["channels"]) == 2
    assert "access_token" not in json.dumps(pending)

    # Connect both channels to the same Project
    complete = client.post(
        f"/api/projects/{project['id']}/channels/connect/youtube/complete",
        json={"selection_id": selection_id, "external_channel_ids": ["UC_CH_1", "UC_CH_2"]},
    )
    assert complete.status_code == 200
    assert len(complete.json()) == 2
    assert len(client.get(f"/api/projects/{project['id']}/channels").json()) == 2

    # Reconnecting an already-connected channel updates it idempotently without duplicating
    single_updated = _mock_youtube_connector(
        channels_payload={
            "items": [
                {"id": "UC_CH_1", "snippet": {"title": "GTA 6 Shorts Renamed", "customUrl": "@gta6shorts"}},
            ]
        },
        token_payload={
            "access_token": "ya29.new-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    monkeypatch.setattr(
        PlatformConnectorFactory, "get_connector", classmethod(lambda cls, p, **kw: single_updated)
    )
    state2 = parse_qs(
        urlparse(client.post(f"/api/projects/{project['id']}/channels/connect/youtube").json()["authorization_url"]).query
    )["state"][0]
    client.get("/api/oauth/youtube/callback", params={"code": "re", "state": state2}, follow_redirects=False)

    channels = client.get(f"/api/projects/{project['id']}/channels").json()
    assert len(channels) == 2
    ch1 = next(c for c in channels if c["external_channel_id"] == "UC_CH_1")
    assert ch1["display_name"] == "GTA 6 Shorts Renamed"
    # Existing refresh token preserved when Google omits refresh_token on re-consent
    creds = channel_service.get_valid_credentials(project["id"], ch1["id"], connector=single_updated)
    assert creds.access_token == "ya29.new-token"

    # Same YouTube channel can also be connected to a second project
    project2 = client.post("/api/projects", json={"name": "Second Brand"}).json()
    state3 = parse_qs(
        urlparse(client.post(f"/api/projects/{project2['id']}/channels/connect/youtube").json()["authorization_url"]).query
    )["state"][0]
    client.get("/api/oauth/youtube/callback", params={"code": "p2", "state": state3}, follow_redirects=False)
    assert len(client.get(f"/api/projects/{project2['id']}/channels").json()) == 1


# ── Token Refresh & Disconnect Lifecycle ─────────────────────────────────────


def test_token_refresh_reauth_required_and_disconnect(client, monkeypatch):
    connector = _mock_youtube_connector()
    _mock_factory(monkeypatch, connector)

    state = _init_state(client)
    client.get("/api/oauth/youtube/callback", params={"code": "c", "state": state}, follow_redirects=False)
    ch = client.get("/api/projects/default/channels").json()[0]

    # 1. Valid non-expired token returned directly
    creds = channel_service.get_valid_credentials("default", ch["id"], connector=connector)
    assert creds.access_token == "ya29.initial-access-token"

    # 2. Expired token refreshes transparently and persists new encrypted token
    with session_scope() as session:
        cred_row = session.scalar(
            select(OAuthCredential).where(OAuthCredential.connected_channel_id == ch["id"])
        )
        cred_row.token_expires_at = utcnow() - timedelta(minutes=5)

    refreshed = channel_service.get_valid_credentials("default", ch["id"], connector=connector)
    assert refreshed.access_token == "ya29.refreshed-access-token"
    with session_scope() as session:
        cred_row = session.scalar(
            select(OAuthCredential).where(OAuthCredential.connected_channel_id == ch["id"])
        )
        assert decrypt_secret(cred_row.encrypted_access_token) == "ya29.refreshed-access-token"

    # 3. Failed refresh with invalid_grant marks channel reauthorization_required
    with session_scope() as session:
        cred_row = session.scalar(
            select(OAuthCredential).where(OAuthCredential.connected_channel_id == ch["id"])
        )
        cred_row.token_expires_at = utcnow() - timedelta(minutes=5)
    bad_refresh = _mock_youtube_connector(refresh_status=400, refresh_payload={"error": "invalid_grant"})
    with pytest.raises(ReauthorizationRequiredError):
        channel_service.get_valid_credentials("default", ch["id"], connector=bad_refresh)

    ch_after_fail = client.get("/api/projects/default/channels").json()[0]
    assert ch_after_fail["status"] == "reauthorization_required"

    # 4. Disconnect purges stored credentials and marks status disconnected
    disc_res = client.post(f"/api/projects/default/channels/{ch['id']}/disconnect")
    assert disc_res.status_code == 200
    assert disc_res.json()["status"] == "disconnected"
    with session_scope() as session:
        cred_after = session.scalar(
            select(OAuthCredential).where(OAuthCredential.connected_channel_id == ch["id"])
        )
        assert cred_after is None
        assert session.get(ConnectedChannel, ch["id"]).status == "disconnected"

    with pytest.raises(ReauthorizationRequiredError):
        channel_service.get_valid_credentials("default", ch["id"], connector=connector)

    # 5. Delete disconnected channel card
    del_res = client.delete(f"/api/projects/default/channels/{ch['id']}")
    assert del_res.status_code == 200
    assert client.get("/api/projects/default/channels").json() == []


# ── Database Migrations & Constraints ────────────────────────────────────────


def test_alembic_upgrade_on_legacy_sqlite_database(tmp_path):
    legacy_db = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy_db)
    conn.executescript(
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, status TEXT NOT NULL,
            current_stage TEXT, error TEXT, options TEXT NOT NULL, claimed_by INTEGER,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO runs VALUES (
            'r1', 'https://youtu.be/1', 'Legacy Run', 'completed', NULL, NULL,
            '{}', NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings VALUES ('llm_provider', 'deepseek');
        """
    )
    conn.commit()
    conn.close()

    url = f"sqlite:///{legacy_db}"
    run_migrations(url)
    try:
        with session_scope(url) as session:
            assert session.execute(select(ConnectedChannel)).all() == []
            from clipyyy.models import Run

            migrated_run = session.get(Run, "r1")
            assert migrated_run is not None
            assert migrated_run.project_id == "default"
    finally:
        dispose_engines()

