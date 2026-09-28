"""Discovery, persistence, and the model passed to newly launched runs."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tests.tyche.test_web import FakeLauncher, _client
from tyche.config import TycheConfig
from tyche.web import models
from tyche.web import server
from fastapi.testclient import TestClient
from tyche.web.settings import VALUE_KEYS


@pytest.fixture(autouse=True)
def clean_model_env(monkeypatch):
    for key in VALUE_KEYS:
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("API_BASE", "https://models.example.test/v1")
    monkeypatch.setenv("API_KEY", "test-secret")
    monkeypatch.setenv("MODEL_NAME", "chat-a")
    monkeypatch.setenv("MODEL_PROVIDER", "OpenAI")


def test_normalize_model_lists():
    result = models.normalize_models({"data": [
        {"id": "chat-b", "context_length": 64000, "top_provider": {"max_completion_tokens": 4096}},
        {"id": "chat-a", "context_window": 32000}, {"id": "chat-b"}, None, 42,
        {"id": "${API_KEY}"}, {"id": "text-embedding-3"}, {"id": "bad space"},
    ]})
    assert [m["id"] for m in result] == ["chat-a", "chat-b"]
    assert result[1]["max_completion_tokens"] == 4096
    assert result[0]["context_length"] == 32000
    assert models.normalize_models({"models": ["chat-a"]})[0]["id"] == "chat-a"
    assert models.normalize_models([{ "name": "chat-b", "context_length": "invalid" }])[0]["context_length"] is None
    with pytest.raises(ValueError):
        models.normalize_models({"error": "not a catalog"})


@pytest.mark.parametrize("base", ["file:///secret", "https://user:pass@example.test", "https://x.test?key=secret", "no-url"])
def test_endpoint_rejects_credential_urls(base):
    with pytest.raises(ValueError):
        models.models_endpoint(base, "OpenAI")


async def test_fetch_paginates_and_uses_provider_auth(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        page = {"data": [{"id": "claude-a"}], "has_more": True, "last_id": "claude-a"} if len(requests) == 1 else {
            "data": [{"id": "claude-b"}], "has_more": False,
        }
        return httpx.Response(200, json=page)

    factory = httpx.AsyncClient
    monkeypatch.setattr(models.httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(handle), **kw))
    endpoint = models.models_endpoint("https://anthropic.example.test", "Anthropic")
    result = await models.fetch_models(endpoint, "Anthropic", "secret")
    assert [m["id"] for m in result] == ["claude-a", "claude-b"]
    assert requests[1].url.params["after_id"] == "claude-a"
    assert requests[0].headers["x-api-key"] == "secret"
    assert requests[0].url.path == "/v1/models"
    assert "authorization" not in requests[0].headers


async def test_fetch_bearer_does_not_follow_redirects(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://elsewhere.test/models"})

    factory = httpx.AsyncClient
    monkeypatch.setattr(models.httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(handle), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        await models.fetch_models("https://models.example.test/v1/models", "OpenAI", "secret")
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer secret"


def test_cache_ttl_refresh_credential_change_and_save(tmp_path, monkeypatch):
    calls = []

    async def fetch(endpoint, provider, key):
        calls.append((endpoint, provider, key))
        return [{"id": f"chat-{len(calls)}"}]

    monkeypatch.setattr(models, "fetch_models", fetch)
    client = _client(tmp_path, env_file=tmp_path / ".env")
    assert client.get("/api/models").json()["source"] == "endpoint"
    cache = client.app.state.tyche.models_cache
    for key, (_, result) in list(cache.items()):
        cache[key] = (time.monotonic() - 60, result)
    client.get("/api/models")
    assert len(calls) == 1  # A successful result with error=None must live for five minutes.
    client.get("/api/models?refresh=true")
    assert len(calls) == 2
    monkeypatch.setenv("API_KEY", "new-secret")
    client.get("/api/models")
    assert len(calls) == 3
    response = client.put("/api/settings/env", json={"secrets": {"API_KEY": "saved-secret"}})
    assert response.status_code == 200
    client.get("/api/models")
    assert len(calls) == 4
    assert "saved-secret" not in json.dumps(cache)


def test_preview_is_temporary_and_uses_draft_credentials(tmp_path, monkeypatch):
    calls = []

    async def fetch(endpoint, provider, key):
        calls.append((endpoint, key))
        return [{"id": "draft-model"}]

    monkeypatch.setattr(models, "fetch_models", fetch)
    env_file = tmp_path / ".env"
    client = _client(tmp_path, env_file=env_file)
    body = {"api_base": "https://new.example.test/v1", "api_key": "draft-secret"}
    reply = client.post("/api/models/discover", json=body)
    assert reply.status_code == 200
    assert calls == [("https://new.example.test/v1/models", "draft-secret")]
    assert not env_file.exists()
    assert "draft-secret" not in reply.text
    assert client.get("/api/meta").json()["env"]["MODEL_NAME"] == "chat-a"
    assert client.post("/api/models/discover", json={"api_base": "https://new.example.test/v1"}).status_code == 422
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [ValueError("secret"), httpx.ReadTimeout("secret")])
def test_failed_discovery_keeps_config_and_redacts_details(tmp_path, monkeypatch, failure):
    async def fail(*_):
        raise failure

    monkeypatch.setattr(models, "fetch_models", fail)
    reply = _client(tmp_path).get("/api/models").json()
    assert reply["source"] == "config" and reply["models"][0]["id"] == "chat-a"
    assert reply["error"] and "secret" not in reply["error"]


def test_all_roles_apply_and_inherit_without_restart(tmp_path):
    client = _client(tmp_path, env_file=tmp_path / ".env")
    response = client.put("/api/settings/env", json={"values": {
        "MODEL_NAME": "default-b", "TYCHE_PLANNER_MODEL_NAME": "planner-b",
        "TYCHE_WRITER_MODEL_NAME": "writer-b", "TYCHE_REVIEW_MODEL_NAME": "review-b",
        "TYCHE_EXPERIMENT_MODEL_NAME": "experiment-b", "TYCHE_SUBJECT_MODEL_NAME": "subject-b",
    }})
    assert response.status_code == 200
    roles = response.json()["roles"]
    assert [roles[r]["model_name"] for r in ["default", "planner", "writer", "reviewer", "experiments", "subject"]] == [
        "default-b", "planner-b", "writer-b", "review-b", "experiment-b", "subject-b",
    ]
    response = client.put("/api/settings/env", json={"values": {"TYCHE_WRITER_MODEL_NAME": ""}})
    assert response.json()["roles"]["writer"]["model_name"] == "default-b"
    assert client.get("/api/meta").json()["model"]["model_name"] == "default-b"


def test_task_picker_overrides_an_explicit_writer_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("TYCHE_WRITER_MODEL_NAME", "old-writer")
    launcher = FakeLauncher()
    client = _client(tmp_path, launcher=launcher)
    reply = client.post("/api/runs", json={"topic": "test topic", "direction": "memory_engine", "model": {"model_name": "selected-writer"}})
    assert reply.status_code == 202
    argv = launcher.spawned[0]["argv"]
    overrides = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--set"]
    assert TycheConfig.load(overrides=overrides).model("writer").model_name == "selected-writer"


@pytest.mark.parametrize("values", [{"MODEL_CONTEXT_WINDOW": "nan"}, {"MODEL_CONTEXT_WINDOW": "0"}, {"MODEL_NAME": "bad name"}])
def test_invalid_settings_do_not_partially_write(tmp_path, values):
    env = tmp_path / ".env"
    env.write_text("MODEL_NAME=chat-a\n", encoding="utf-8")
    client = _client(tmp_path, env_file=env)
    reply = client.put("/api/settings/env", json={"values": values, "secrets": {"API_KEY": "replacement-secret"}})
    assert reply.status_code == 422
    assert env.read_text() == "MODEL_NAME=chat-a\n"
    assert "replacement-secret" not in reply.text


def test_concurrent_model_saves_and_reads_are_serialized(tmp_path, monkeypatch):
    client = _client(tmp_path, env_file=tmp_path / ".env")
    original_save, original_reload = server.apply_env_updates, server._reload_env
    writing = False

    def save(*args, **kwargs):
        nonlocal writing
        assert not writing
        writing = True
        try:
            time.sleep(0.02)
            return original_save(*args, **kwargs)
        finally:
            writing = False

    def reload(*args):
        assert not writing, "A request read the dotenv file during replacement"
        return original_reload(*args)

    monkeypatch.setattr(server, "apply_env_updates", save)
    monkeypatch.setattr(server, "_reload_env", reload)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = []
        for i in range(4):
            futures.append(pool.submit(client.put, "/api/settings/env", json={"values": {"MODEL_NAME": f"chat-{i}"}}))
            futures.append(pool.submit(client.get, "/api/meta"))
        assert all(future.result().status_code == 200 for future in futures)


def test_server_override_cannot_silently_ignore_a_selection(tmp_path):
    env_file = tmp_path / ".env"
    app = server.create_app(tmp_path, env_file=env_file, overrides=["models.writer.model_name=fixed-model"])
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.put("/api/settings/env", json={"values": {"TYCHE_WRITER_MODEL_NAME": "selected-model"}})
    assert response.status_code == 422
    assert "overridden" in response.json()["error"]["message"]
    assert not env_file.exists()
