import pytest
from fastapi.testclient import TestClient

from clipyyy import db
from clipyyy.api import create_app


@pytest.fixture
def client():
    with TestClient(create_app(start_worker=False)) as c:
        yield c


def test_settings_are_masked_and_updatable(client):
    r = client.put(
        "/api/settings",
        json={
            "values": {
                "openrouter_api_key": "sk-or-1234567890abcd",
                "deepseek_api_key": "sk-ds-1234567890wxyz",
                "llm_provider": "deepseek",
                "llm_model": "a/b",
            }
        },
    )
    assert r.status_code == 200
    rows = {s["key"]: s for s in client.get("/api/settings").json()}
    assert rows["openrouter_api_key"]["value"] == "sk-••••abcd"
    assert rows["openrouter_api_key"]["source"] == "app"
    assert rows["deepseek_api_key"]["value"] == "sk-••••wxyz"
    assert rows["deepseek_api_key"]["source"] == "app"
    assert rows["llm_provider"]["value"] == "deepseek"
    assert rows["llm_model"]["value"] == "a/b"
    # Sending the masked value back must not overwrite the real key
    client.put("/api/settings", json={"values": {"openrouter_api_key": "sk-••••abcd"}})
    assert db.get_setting("openrouter_api_key") == "sk-or-1234567890abcd"
    client.put("/api/settings", json={"values": {"openrouter_api_key": None}})
    assert db.get_setting("openrouter_api_key") is None
    assert client.put("/api/settings", json={"values": {"nope": "x"}}).status_code == 400


def test_api_providers_endpoint(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert "deepseek" in ids and "openrouter" in ids and "ollama" in ids


def test_api_test_connection_endpoint(client):
    # Fails when key is missing
    r = client.post("/api/settings/test-connection", json={"provider": "deepseek", "api_key": ""})
    assert r.status_code == 400
    assert "No API key" in r.json()["detail"]


def test_run_lifecycle(client):
    r = client.post(
        "/api/runs",
        json={"sources": ["https://youtu.be/abc", " "], "options": {"clip_count": 2, "aspect_ratio": "1:1"}},
    )
    assert r.status_code == 200 and len(r.json()) == 1
    run = r.json()[0]
    assert run["status"] == "queued" and run["options"]["clip_count"] == 2

    detail = client.get(f"/api/runs/{run['id']}").json()
    assert [s["name"] for s in detail["stages"]][:3] == ["download", "transcribe", "select"]
    assert all(s["status"] == "pending" for s in detail["stages"])

    assert client.post(f"/api/runs/{run['id']}/retry").status_code == 409
    db.update_run(run["id"], status="failed")
    assert client.post(f"/api/runs/{run['id']}/retry", json={"from_stage": "bogus"}).status_code == 400
    assert (
        client.post(f"/api/runs/{run['id']}/retry", json={"from_stage": "select"}).json()["status"]
        == "queued"
    )

    assert client.get(f"/api/runs/{run['id']}/download").status_code == 404
    assert client.delete(f"/api/runs/{run['id']}").status_code == 200
    assert client.get(f"/api/runs/{run['id']}").status_code == 404


def test_invalid_options_rejected(client):
    r = client.post("/api/runs", json={"sources": ["x"], "options": {"min_seconds": 50, "max_seconds": 51}})
    assert r.status_code == 422


def test_upload_and_health(client):
    r = client.post("/api/uploads", files={"file": ("talk.mp4", b"data", "video/mp4")})
    assert r.status_code == 200 and r.json()["name"] == "talk.mp4"
    checks = {c["name"]: c for c in client.get("/api/health").json()["checks"]}
    assert checks["llm"]["ok"] is False


def test_buffer_without_key(client):
    assert client.get("/api/buffer/channels").status_code == 400
