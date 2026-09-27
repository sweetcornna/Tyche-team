"""Tests for the ``tyche ui`` web backend: ``tyche/web/{server,runs,processes,settings}.py``."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.tyche.conftest import needs_latex
from tyche.config import DIRECTIONS
from tyche.selftest import run_selftest
from tyche.web.server import create_app
from tyche.web.settings import SettingsError, apply_env_updates
from tyche.workspace import Workspace

_MISSING_STATIC = Path("/nonexistent-tyche-frontend-dist")


class FakeLauncher:
    """Records what would have been spawned instead of starting a real ``tyche run``."""

    def __init__(self):
        self.spawned: list[dict[str, Any]] = []
        self.stopped: list[tuple[str, dict[str, Any]]] = []

    def spawn(self, argv, *, cwd, log_path, run_id):
        self.spawned.append({"argv": argv, "cwd": cwd, "log_path": log_path, "run_id": run_id})
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"=== launch: {' '.join(argv)} ===\n", encoding="utf-8")
        return {"pid": 424242, "started_at": "2026-01-01T00:00:00+00:00", "source": "web"}

    def stop(self, run_id, process):
        self.stopped.append((run_id, process))


def _client(tmp_path: Path, *, launcher: FakeLauncher | None = None, env_file: Path | None = None) -> TestClient:
    app = create_app(tmp_path, static_dir=_MISSING_STATIC, launcher=launcher, env_file=env_file)
    return TestClient(app, base_url="http://127.0.0.1")


def _mark_all_done(ws: Workspace) -> None:
    from tyche import STAGES

    for stage in STAGES:
        ws.mark_stage(stage, "done")


# -- meta / no secret leakage -------------------------------------------------


def test_meta_shape_and_no_secret_leakage(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "top-secret-value")
    monkeypatch.setenv("S2_API_KEY", "")
    monkeypatch.setenv("MODEL_NAME", "gpt-6-luna")
    ws = Workspace.create(tmp_path, "run1", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("plan", "done", title="A title")
    client = _client(tmp_path)

    meta = client.get("/api/meta").json()
    assert set(DIRECTIONS) <= {d["name"] for d in meta["directions"]}
    assert meta["stages"][0] == "plan"
    assert meta["keys"] == {"API_KEY": True, "S2_API_KEY": False, "OPENALEX_API_KEY": False}
    assert "reasoning_levels" in meta and "max" in meta["reasoning_levels"]
    blob = json.dumps(meta)
    assert "top-secret-value" not in blob

    detail = client.get("/api/runs/run1").json()
    assert "top-secret-value" not in json.dumps(detail)
    listing = client.get("/api/runs").json()
    assert "top-secret-value" not in json.dumps(listing)


# -- run listing / status derivation -----------------------------------------


def test_run_status_done(tmp_path):
    ws = Workspace.create(tmp_path, "run-done", topic="t", direction="memory_engine", config_digest="x")
    _mark_all_done(ws)
    client = _client(tmp_path)
    row = client.get("/api/runs/run-done").json()
    assert row["status"] == "done"
    assert row["stages_done"] == row["stages_total"]


def test_run_status_paused_via_stop_after(tmp_path):
    ws = Workspace.create(tmp_path, "run-paused", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("plan", "done")
    ws.mark_stage("survey", "done")
    client = _client(tmp_path)
    row = client.get("/api/runs/run-paused").json()
    assert row["status"] == "paused"
    assert row["stage"] == "experiments"


def test_run_status_stopped_when_running_without_process(tmp_path):
    ws = Workspace.create(tmp_path, "run-stopped", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("plan", "done")
    ws.mark_stage("survey", "running")
    client = _client(tmp_path)
    row = client.get("/api/runs/run-stopped").json()
    assert row["status"] == "stopped"
    assert row["process"] is None


def test_run_status_failed_with_error_message(tmp_path):
    ws = Workspace.create(tmp_path, "run-failed", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("plan", "done")
    ws.mark_stage("survey", "failed", error="StageError: no papers found")
    client = _client(tmp_path)
    row = client.get("/api/runs/run-failed").json()
    assert row["status"] == "failed"
    detail = client.get("/api/runs/run-failed").json()
    survey_row = next(s for s in detail["stages"] if s["name"] == "survey")
    assert survey_row["error"] == "StageError: no papers found"


def test_run_status_pending_and_list_archived_filter(tmp_path):
    Workspace.create(tmp_path, "run-pending", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path)
    row = client.get("/api/runs/run-pending").json()
    assert row["status"] == "pending"
    assert row["stage"] == "plan"
    client.patch("/api/runs/run-pending", json={"archived": True})
    active = client.get("/api/runs?archived=false").json()["runs"]
    assert all(r["run_id"] != "run-pending" for r in active)
    archived = client.get("/api/runs?archived=true").json()["runs"]
    assert any(r["run_id"] == "run-pending" for r in archived)


def test_run_not_found(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/runs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "run_not_found"


# -- detail: stages / durations / usage --------------------------------------


def test_run_detail_stages_durations_usage(tmp_path):
    ws = Workspace.create(tmp_path, "run-usage", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("plan", "running")
    ws.mark_stage("plan", "done", title="hello", method="Method X")
    usage_path = ws.run_dir / "usage.jsonl"
    usage_path.write_text(
        json.dumps(
            {
                "purpose": "plan",
                "stage": "plan",
                "model": "gpt-6-luna",
                "input_tokens": 100,
                "output_tokens": 20,
                "latency_s": 1.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = _client(tmp_path)
    detail = client.get("/api/runs/run-usage").json()
    plan_row = next(s for s in detail["stages"] if s["name"] == "plan")
    assert plan_row["status"] == "done"
    assert plan_row["summary"]["method"] == "Method X"
    assert plan_row["duration_s"] is not None and plan_row["duration_s"] >= 0
    assert detail["usage"]["total"]["input_tokens"] == 100
    assert detail["usage"]["by_model"]["gpt-6-luna"]["calls"] == 1
    assert detail["title"] == "hello"


# -- events since/limit + path stripping --------------------------------------


def test_events_since_limit_and_path_stripping(tmp_path):
    ws = Workspace.create(tmp_path, "run-events", topic="t", direction="memory_engine", config_digest="x")
    outside = tmp_path / "elsewhere" / "report.pdf"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("x", encoding="utf-8")
    inside = ws.run_dir / "package" / "paper.pdf"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("x", encoding="utf-8")
    ws.event("custom.paths", pdf=str(inside), dir=str(outside))
    client = _client(tmp_path)

    page = client.get("/api/runs/run-events/events?since=0&limit=1").json()
    assert len(page["events"]) == 1
    assert page["events"][0]["seq"] == 0
    assert page["next"] == 1

    full = client.get("/api/runs/run-events/events?since=0&limit=100").json()
    custom = next(e for e in full["events"] if e["kind"] == "custom.paths")
    assert custom["pdf"] == "package/paper.pdf"
    assert custom["dir"] == "report.pdf"


# -- references cited flag ----------------------------------------------------


def test_references_cited_flag(tmp_path):
    ws = Workspace.create(tmp_path, "run-refs", topic="t", direction="memory_engine", config_digest="x")
    manifest = {
        "papers": [
            {"key": "fixture2024cited", "title": "Cited Fixture Paper", "authors": ["A Fixture"], "year": 2024,
             "arxiv_id": "0000.00001", "url": "https://arxiv.org/abs/0000.00001"},
            {"key": "fixture2024uncited", "title": "Uncited Fixture Paper", "authors": ["B Fixture"], "year": 2024,
             "arxiv_id": "0000.00002", "url": "https://arxiv.org/abs/0000.00002"},
        ],
        "excluded": [],
        "stats": {"kept": 2},
        "synthesis": {},
        "evidence_cards": [{"key": "fixture2024cited", "claim": "a claim", "quote": "q"}],
    }
    ws.save_json("source_manifest", manifest, stage="survey")
    source_dir = ws.run_dir / "package" / "paper_source" / "sections"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "method.tex").write_text("As shown by \\citep{fixture2024cited}.", encoding="utf-8")
    client = _client(tmp_path)

    refs = client.get("/api/runs/run-refs/references").json()
    by_key = {p["key"]: p for p in refs["papers"]}
    assert by_key["fixture2024cited"]["cited"] is True
    assert by_key["fixture2024uncited"]["cited"] is False
    assert len(by_key["fixture2024cited"]["cards"]) == 1


def test_references_missing_manifest_404(tmp_path):
    Workspace.create(tmp_path, "run-norefs", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path)
    resp = client.get("/api/runs/run-norefs/references")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "no_references"


# -- experiments: live / timeline / files from a fabricated attempt ----------


def _make_attempt(run_dir: Path, attempt: str, *, terminal: bool) -> Path:
    attempt_dir = run_dir / "experiments" / "engine" / "experiments" / attempt
    manager_dir = attempt_dir / "manager"
    manager_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {"ts": "2026-01-01T00:00:00Z", "event": "manager_start", "module": "manager", "round": 0},
        {"ts": "2026-01-01T00:00:05Z", "event": "manager_execute", "module": "code_implementation", "round": 1,
         "outcome": None},
        {"ts": "2026-01-01T00:00:10Z", "event": "subagent_finish", "module": "code_implementation", "round": 1,
         "outcome": "ok"},
    ]
    with (manager_dir / "events.jsonl").open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    state = {"terminal": {"status": "complete"} if terminal else None}
    (manager_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    trace_dir = attempt_dir / "modules" / "code_implementation" / "round_001_attempt_001"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace = [
        {"seq": 0, "ts": "2026-01-01T00:00:06Z", "event": "model_call_start", "call_id": "m1"},
        {"seq": 1, "ts": "2026-01-01T00:00:08Z", "event": "model_call_end", "call_id": "m1"},
    ]
    with (trace_dir / "agent_trace.jsonl").open("w", encoding="utf-8") as fh:
        for ev in trace:
            fh.write(json.dumps(ev) + "\n")
    output_dir = attempt_dir / "agent_workspace" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run.py").write_text("print('hi')\n", encoding="utf-8")
    (output_dir / "results").mkdir(exist_ok=True)
    return attempt_dir


def test_experiments_live_timeline_files(tmp_path):
    ws = Workspace.create(tmp_path, "run-exp", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("plan", "done")
    ws.mark_stage("survey", "done")
    ws.mark_stage("experiments", "running", engine="openjiuwen", variants=["proposed", "baseline"])
    _make_attempt(ws.run_dir, "tyche-run-exp-a1", terminal=False)
    client = _client(tmp_path)

    detail = client.get("/api/runs/run-exp/experiments").json()
    assert detail["attempts"] == ["tyche-run-exp-a1"]
    assert len(detail["timeline"]) == 3
    assert detail["timeline"][0]["event"] == "manager_start"
    assert detail["live"] is not None
    assert detail["live"]["attempt"] == "tyche-run-exp-a1"
    assert detail["live"]["module"] == "code_implementation"
    assert detail["live"]["model_calls"] == 1
    assert detail["files_root"] == "live"
    assert {f["path"] for f in detail["files"]} == {"run.py"}


def test_experiments_live_module_is_the_open_subagent(tmp_path):
    ws = Workspace.create(tmp_path, "run-exec", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("experiments", "running", engine="openjiuwen", variants=["proposed", "baseline"])
    attempt = _make_attempt(ws.run_dir, "tyche-run-exec-a1", terminal=False)
    with (attempt / "manager" / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-01-01T00:01:00Z", "event": "subagent_start", "module": "experiment_execution",
                             "round": 2}) + "\n")
    # The manager's own trace is newer, but the running sub-agent is what the user should see.
    manager_trace = attempt / "modules" / "manager" / "round_002_attempt_001" / "agent_trace.jsonl"
    manager_trace.parent.mkdir(parents=True)
    manager_trace.write_text(json.dumps({"ts": "2026-01-01T00:01:01Z", "event": "model_call_start"}) + "\n", encoding="utf-8")
    live = _client(tmp_path).get("/api/runs/run-exec/experiments").json()["live"]
    assert live["module"] == "experiment_execution" and live["round"] == 2
    assert live["model_calls"] == 0 and live["since"] == "2026-01-01T00:01:00Z"


def test_experiments_no_live_when_terminal(tmp_path):
    ws = Workspace.create(tmp_path, "run-exp-done", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("experiments", "done", engine="openjiuwen", variants=["proposed"])
    _make_attempt(ws.run_dir, "tyche-run-exp-done-a1", terminal=True)
    client = _client(tmp_path)
    detail = client.get("/api/runs/run-exp-done/experiments").json()
    assert detail["live"] is None
    assert detail["status"] == "completed"


def test_experiment_file_traversal_rejected(tmp_path):
    ws = Workspace.create(tmp_path, "run-trav", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("experiments", "running", engine="openjiuwen", variants=["proposed"])
    _make_attempt(ws.run_dir, "tyche-run-trav-a1", terminal=False)
    client = _client(tmp_path)

    ok = client.get("/api/runs/run-trav/experiments/file", params={"path": "run.py"})
    assert ok.status_code == 200
    assert "print" in ok.text

    escaped = client.get("/api/runs/run-trav/experiments/file", params={"path": "../../../etc/passwd"})
    assert escaped.status_code == 400
    assert escaped.json()["error"]["code"] == "invalid_path"

    missing = client.get("/api/runs/run-trav/experiments/file", params={"path": "no-such-file.py"})
    assert missing.status_code == 404


# -- artifacts listing + directory artifact file access ----------------------


def test_artifacts_listing_and_dir_artifact_file(tmp_path):
    ws = Workspace.create(tmp_path, "run-art", topic="t", direction="memory_engine", config_digest="x")
    ws.save_json("plan", {"a": 1}, stage="plan")
    ws.save_json("plan", {"a": 2}, stage="plan")
    tree_src = tmp_path / "tree_src"
    (tree_src / "sub").mkdir(parents=True)
    (tree_src / "main.tex").write_text("hello", encoding="utf-8")
    (tree_src / "sub" / "figure.pdf").write_text("pdfdata", encoding="utf-8")
    ws.save_tree("paper_source", tree_src, stage="review")
    client = _client(tmp_path)

    listing = client.get("/api/runs/run-art/artifacts").json()["artifacts"]
    plan_art = next(a for a in listing if a["name"] == "plan")
    assert plan_art["kind"] == "json"
    assert [v["version"] for v in plan_art["versions"]] == [1, 2]
    tree_art = next(a for a in listing if a["name"] == "paper_source")
    assert tree_art["kind"] == "dir"

    version_resp = client.get("/api/runs/run-art/artifacts/plan/2")
    assert version_resp.status_code == 200
    assert version_resp.json() == {"a": 2}

    dir_resp = client.get("/api/runs/run-art/artifacts/paper_source/1")
    assert dir_resp.status_code == 200
    paths = {f["path"] for f in dir_resp.json()["files"]}
    assert paths == {"main.tex", "sub/figure.pdf"}

    file_resp = client.get("/api/runs/run-art/artifacts/paper_source/1", params={"path": "sub/figure.pdf"})
    assert file_resp.status_code == 200
    assert file_resp.text == "pdfdata"

    traversal = client.get("/api/runs/run-art/artifacts/paper_source/1", params={"path": "../../outside"})
    assert traversal.status_code == 400


# -- POST /api/runs validation + launch --------------------------------------


def test_post_runs_validation_errors(tmp_path):
    client = _client(tmp_path, launcher=FakeLauncher())
    too_short = client.post("/api/runs", json={"topic": "ab", "direction": "memory_engine"})
    assert too_short.status_code == 422
    assert too_short.json()["error"]["code"] == "invalid_topic"

    bad_direction = client.post("/api/runs", json={"topic": "a fine topic", "direction": "nope"})
    assert bad_direction.status_code == 422
    assert bad_direction.json()["error"]["code"] == "invalid_direction"

    bad_run_id = client.post(
        "/api/runs", json={"topic": "a fine topic", "direction": "memory_engine", "run_id": "AB"}
    )
    assert bad_run_id.status_code == 422
    assert bad_run_id.json()["error"]["code"] == "invalid_run_id"

    needs_results_dir = client.post(
        "/api/runs", json={"topic": "a fine topic", "direction": "memory_engine", "engine": "imported"}
    )
    assert needs_results_dir.status_code == 422
    assert needs_results_dir.json()["error"]["code"] == "results_dir_required"

    bad_pages = client.post(
        "/api/runs",
        json={"topic": "a fine topic", "direction": "memory_engine", "settings": {"max_main_pages": 20}},
    )
    assert bad_pages.status_code == 422
    assert bad_pages.json()["error"]["code"] == "invalid_max_main_pages"


def test_run_requests_cannot_smuggle_settings_or_paths(tmp_path):
    launcher = FakeLauncher()
    client = _client(tmp_path, launcher=launcher)
    base = {"topic": "A fine research topic", "direction": "memory_engine"}
    for name in ("${API_KEY}", "m #x", "a b", "{x}", "m\n"):
        resp = client.post("/api/runs", json={**base, "model": {"model_name": name}})
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_model_name", name
    bad_reviewer = client.post("/api/runs", json={**base, "model": {"reviewer_model": "$HOME"}})
    assert bad_reviewer.json()["error"]["code"] == "invalid_reviewer_model"
    assert client.post("/api/runs", json={**base, "run_id": "my-run\n"}).status_code == 422
    assert not launcher.spawned
    # A topic that looks like a flag stays the topic.
    assert client.post("/api/runs", json={**base, "topic": "--stop-after plan"}).status_code == 202
    assert "--topic=--stop-after plan" in launcher.spawned[0]["argv"]
    for run_id in ("..", ".hidden", "a%2Fb"):
        assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_post_runs_launch_with_fake_launcher(tmp_path):
    launcher = FakeLauncher()
    client = _client(tmp_path, launcher=launcher)
    body = {
        "topic": "A fine research topic",
        "direction": "memory_engine",
        "run_id": "my-run-1",
        "notes": "please focus on X",
        "model": {"model_name": "gpt-6-luna", "reasoning_effort": "high"},
        "settings": {"review_max_rounds": 2, "max_main_pages": 4},
    }
    resp = client.post("/api/runs", json=body)
    assert resp.status_code == 202
    assert resp.json()["run_id"] == "my-run-1"
    assert resp.json()["process"]["pid"] == 424242

    assert len(launcher.spawned) == 1
    argv = launcher.spawned[0]["argv"]
    assert launcher.spawned[0]["run_id"] == "my-run-1"
    assert str(tmp_path) in argv
    assert "--run-id" in argv and "my-run-1" in argv
    assert "--set" in argv and 'models.default.model_name="gpt-6-luna"' in argv
    assert "--topic=A fine research topic" in argv
    assert any("review.max_rounds=2" in a for a in argv)
    assert any("paper.max_main_pages=4" in a for a in argv)
    assert "--notes" in argv
    notes_path = Path(argv[argv.index("--notes") + 1])
    assert notes_path.read_text(encoding="utf-8") == "please focus on X"

    # Simulate the spawned process having created the run directory (a fake launcher does not).
    Workspace.create(tmp_path, "my-run-1", topic="already exists", direction="memory_engine", config_digest="x")
    dup = client.post("/api/runs", json={"topic": "A fine topic again", "direction": "memory_engine", "run_id": "my-run-1"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "run_exists"


# -- resume / stop 409s -------------------------------------------------------


def test_resume_unknown_run_404(tmp_path):
    client = _client(tmp_path, launcher=FakeLauncher())
    resp = client.post("/api/runs/no-such-run/resume", json={})
    assert resp.status_code == 404


def test_stop_not_running_409(tmp_path):
    Workspace.create(tmp_path, "run-stop", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path, launcher=FakeLauncher())
    resp = client.post("/api/runs/run-stop/stop")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_running"


def test_resume_already_running_409(tmp_path, monkeypatch):
    Workspace.create(tmp_path, "run-live", topic="t", direction="memory_engine", config_digest="x")
    launcher = FakeLauncher()
    client = _client(tmp_path, launcher=launcher)
    from tyche.web.processes import ProcessRegistry

    monkeypatch.setattr(
        ProcessRegistry, "live_process", lambda self, run_id: {"pid": 1, "started_at": "now", "source": "cli"}
    )
    resp = client.post("/api/runs/run-live/resume", json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_running"


# -- PATCH metadata -----------------------------------------------------------


def test_patch_metadata(tmp_path):
    Workspace.create(tmp_path, "run-patch", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path)
    resp = client.patch("/api/runs/run-patch", json={"title": "New title", "pinned": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "New title"
    assert body["pinned"] is True

    cleared = client.patch("/api/runs/run-patch", json={"title": ""})
    assert cleared.json()["title"] == "t"


# -- DELETE moves to trash -----------------------------------------------------


def test_delete_moves_to_trash(tmp_path):
    Workspace.create(tmp_path, "run-del", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path)
    client.patch("/api/runs/run-del", json={"pinned": True})
    resp = client.delete("/api/runs/run-del")
    assert resp.status_code == 200
    trashed_rel = resp.json()["trashed"]
    assert (tmp_path / trashed_rel).is_dir()
    assert not (tmp_path / "runs" / "run-del").exists()
    assert client.get("/api/runs/run-del").status_code == 404
    ui_meta = json.loads((tmp_path / ".tyche-web" / "runs.json").read_text(encoding="utf-8"))
    assert "run-del" not in ui_meta


# -- settings env write --------------------------------------------------------


def test_settings_env_write_preserves_lines_and_hides_secrets(tmp_path):
    env_path = tmp_path / "test.env"
    env_path.write_text("# a comment\nAPI_KEY=old\nUNRELATED_KEY=keep-me\n", encoding="utf-8")
    client = _client(tmp_path, env_file=env_path)

    resp = client.put(
        "/api/settings/env", json={"values": {"MODEL_NAME": "new-model"}, "secrets": {"API_KEY": "brand-new-secret"}}
    )
    assert resp.status_code == 200
    assert "brand-new-secret" not in json.dumps(resp.json())
    text = env_path.read_text(encoding="utf-8")
    assert "# a comment" in text
    assert "UNRELATED_KEY=keep-me" in text
    assert "API_KEY='brand-new-secret'" in text
    assert "MODEL_NAME='new-model'" in text

    unknown = client.put("/api/settings/env", json={"values": {"NOT_A_REAL_KEY": "x"}})
    assert unknown.status_code == 422

    newline = client.put("/api/settings/env", json={"secrets": {"API_KEY": "line1\nline2"}})
    assert newline.status_code == 422
    # A reference to another variable would copy that secret into a logged setting.
    for value in ("${API_KEY}", "a'b", "a\\b", "`id`"):
        assert client.put("/api/settings/env", json={"values": {"API_BASE": value}}).status_code == 422


def test_env_values_are_read_back_literally(tmp_path, monkeypatch):
    from dotenv import dotenv_values

    env_path = tmp_path / "lit.env"
    env_path.write_text("API_KEY=sk-test-secret\n", encoding="utf-8")
    apply_env_updates(env_path, values={"API_BASE": "https://example.test/v1#frag", "MODEL_NAME": "m # x"})
    assert dotenv_values(env_path, interpolate=False) == {
        "API_KEY": "sk-test-secret", "API_BASE": "https://example.test/v1#frag", "MODEL_NAME": "m # x"
    }
    # A hand-written reference stays literal when the server reloads the file.
    env_path.write_text("API_KEY=sk-test-secret\nAPI_BASE=https://h/${API_KEY}\n", encoding="utf-8")
    monkeypatch.delenv("API_BASE", raising=False)
    from tyche.web.server import _reload_env

    _reload_env(env_path)
    import os

    assert os.environ["API_BASE"] == "https://h/${API_KEY}"


def test_apply_env_updates_creates_file_atomically(tmp_path):
    env_path = tmp_path / "fresh.env"
    updates = apply_env_updates(env_path, values={"API_BASE": "https://example.test/v1"})
    assert updates == {"API_BASE": "https://example.test/v1"}
    assert env_path.read_text(encoding="utf-8").strip() == "API_BASE='https://example.test/v1'"
    assert (env_path.stat().st_mode & 0o777) == 0o600
    with pytest.raises(SettingsError):
        apply_env_updates(env_path, values={"NOT_ALLOWED": "x"})
    env_path.write_text("MODEL_NAME=a\n# keep\nMODEL_NAME=b\n", encoding="utf-8")
    apply_env_updates(env_path, values={"MODEL_NAME": "c"})
    assert env_path.read_text(encoding="utf-8") == "MODEL_NAME='c'\n# keep\n"


# -- Host/Origin guard ---------------------------------------------------------


def test_host_guard_rejects_unknown_host(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/meta", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_host"


def test_origin_guard_rejects_cross_origin_write(tmp_path):
    Workspace.create(tmp_path, "run-origin", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path)
    resp = client.patch(
        "/api/runs/run-origin", json={"pinned": True}, headers={"Origin": "http://evil.example.com:9999"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden_origin"


def test_origin_guard_allows_own_origin(tmp_path):
    Workspace.create(tmp_path, "run-ok", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path)
    resp = client.patch(
        "/api/runs/run-ok", json={"pinned": True}, headers={"Origin": "http://127.0.0.1:8765"}
    )
    assert resp.status_code == 200


# -- SPA fallback / not-built page ----------------------------------------------


def test_spa_fallback_shows_not_built_page(tmp_path):
    client = _client(tmp_path)
    root = client.get("/")
    assert root.status_code == 200
    assert "not built" in root.text.lower()
    other = client.get("/some/deep/route")
    assert other.status_code == 200
    assert "not built" in other.text.lower()
    unknown_api = client.get("/api/does-not-exist")
    assert unknown_api.status_code == 404


def test_spa_serves_built_index(tmp_path):
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>tyche ui</html>", encoding="utf-8")
    assets = static_dir / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(tmp_path / "ws", static_dir=static_dir)
    client = TestClient(app, base_url="http://127.0.0.1")

    root = client.get("/")
    assert root.status_code == 200 and "tyche ui" in root.text

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"].startswith("public")

    deep = client.get("/some/deep/route")
    assert deep.status_code == 200 and "tyche ui" in deep.text


# -- library / lessons ---------------------------------------------------------


def test_library_lists_runs_with_papers(tmp_path):
    ws = Workspace.create(tmp_path, "run-lib", topic="t", direction="memory_engine", config_digest="x")
    ws.mark_stage("review", "done", composite=6.5)
    package = ws.run_dir / "package"
    package.mkdir(exist_ok=True)
    (package / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    client = _client(tmp_path)
    library = client.get("/api/library").json()["papers"]
    assert any(p["run_id"] == "run-lib" for p in library)
    row = next(p for p in library if p["run_id"] == "run-lib")
    assert row["composite"] == 6.5
    assert row["pdf_url"] == "/api/runs/run-lib/files/paper.pdf"


def test_lessons_empty_without_memory_db(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/lessons").json() == {"lessons": []}


# -- full pipeline output via the offline selftest ---------------------------


@needs_latex
def test_full_run_detail_paper_and_analysis(tmp_path):
    asyncio.run(run_selftest(root=tmp_path, run_id="full-run"))
    client = _client(tmp_path)

    detail = client.get("/api/runs/full-run").json()
    assert detail["status"] == "done"
    assert detail["has_paper"] is True
    assert detail["paper"]["source"] == "package"
    assert detail["paper"]["unverified"] is False

    pdf = client.get("/api/runs/full-run/files/paper.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"

    analysis = client.get("/api/runs/full-run/analysis").json()
    assert "figure_url" in analysis

    ledger = client.get("/api/runs/full-run/ledger").json()
    assert "entries" in ledger

    report = client.get("/api/runs/full-run/report")
    assert report.status_code == 200
    assert "Tyche run report" in report.text

    claims = client.get("/api/runs/full-run/claims").json()
    assert claims["stats"]["claims"] > 0 and claims["stats"]["unverified"] == 0
    assert client.get("/api/runs/full-run/revisions").json()["rounds"]
    lineage = client.get("/api/runs/full-run/lineage").json()
    assert {n["name"] for n in lineage["nodes"]} >= {"plan", "paper"}
    env = client.get("/api/runs/full-run/environment").json()
    assert env["tyche"]["version"] and "captured_at" in env
    packaged = json.loads((tmp_path / "runs" / "full-run" / "package" / "claims.json").read_text(encoding="utf-8"))
    assert packaged["stats"] == claims["stats"]
    assert "Claim-evidence map" in report.text


def test_trace_endpoints_before_a_paper_exists(tmp_path):
    Workspace.create(tmp_path, "run-early", topic="t", direction="memory_engine", config_digest="x")
    client = _client(tmp_path)
    assert client.get("/api/runs/run-early/claims").json()["error"]["code"] == "no_paper"
    assert client.get("/api/runs/run-early/revisions").json()["rounds"] == []
    assert client.get("/api/runs/run-early/lineage").json()["nodes"] == []
    assert client.get("/api/runs/run-early/environment").status_code == 404


def test_resume_from_stage_with_notes_builds_argv(tmp_path):
    Workspace.create(tmp_path, "run-again", topic="t", direction="memory_engine", config_digest="x")
    launcher = FakeLauncher()
    client = _client(tmp_path, launcher=launcher)
    resp = client.post(
        "/api/runs/run-again/resume", json={"from_stage": "plan", "stop_after": "plan", "notes": "Use three baselines."}
    )
    assert resp.status_code == 202
    argv = launcher.spawned[-1]["argv"]
    assert argv[argv.index("--from-stage") + 1] == "plan" and argv[argv.index("--stop-after") + 1] == "plan"
    notes_path = Path(argv[argv.index("--notes") + 1])
    assert notes_path.read_text(encoding="utf-8") == "Use three baselines."
    assert "--stage" not in argv
    both = client.post("/api/runs/run-again/resume", json={"stage": "write", "from_stage": "write"})
    assert both.status_code == 422
    assert client.post("/api/runs/run-again/resume", json={"from_stage": "nope"}).status_code == 422
    # Notes steer planning only; sent with a later stage they would be silently ignored.
    late = client.post("/api/runs/run-again/resume", json={"from_stage": "write", "notes": "x"})
    assert late.status_code == 422 and late.json()["error"]["code"] == "notes_need_replan"


def test_resume_keeps_the_run_config_instead_of_the_servers(tmp_path):
    Workspace.create(tmp_path, "run-own", topic="t", direction="memory_engine", config_digest="x")
    launcher = FakeLauncher()
    app = create_app(tmp_path, static_dir=_MISSING_STATIC, launcher=launcher, overrides=["review.max_rounds=9"])
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.post("/api/runs/run-own/resume", json={}).status_code == 202
    assert "review.max_rounds=9" not in launcher.spawned[-1]["argv"]
    assert client.post("/api/runs", json={"topic": "A new topic", "direction": "memory_engine"}).status_code == 202
    assert "review.max_rounds=9" in launcher.spawned[-1]["argv"]


def test_cli_process_detection_reads_every_run_id_form(tmp_path):
    from tyche.web.processes import _matches_run, _run_of

    py = ["/usr/bin/python3", "-m", "tyche", "run"]
    assert _run_of([*py, "--run-id", "a1"]) == ("a1", None)
    assert _run_of([*py, "--run-id=a1"]) == ("a1", None)
    assert _run_of([*py, "--run", "a1", "--resume"]) == ("a1", None)
    assert _run_of([*py, "--resume"]) is None
    assert _run_of(["/usr/bin/python3", "other.py", "run", "--run-id", "a1"]) is None
    assert _run_of([*py, "--workspace=/w", "--run-id", "a1"]) == ("a1", "/w")
    here = [*py, "--run-id", "a1", "--workspace", str(tmp_path)]
    assert _matches_run(here, "a1", tmp_path)
    assert not _matches_run([*py, "--run-id", "a1", "--workspace", str(tmp_path / "elsewhere")], "a1", tmp_path)
    assert _matches_run([*py, "--run-id", "a1", "--workspace", "ws"], "a1", tmp_path / "ws", cwd=str(tmp_path))
    assert _matches_run([*py, "--run-id", "a1"], "a1", tmp_path)  # workspace from config: cannot tell, assume same


def test_stop_ends_children_that_left_the_process_group(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time

    import psutil

    from tyche.web import processes
    from tyche.web.processes import Launcher, ProcessRegistry

    monkeypatch.setattr(processes, "_STOP_WAIT_S", 2.0)
    child_pid = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
        f"open({str(child_pid)!r}, 'w').write(str(c.pid))\n"
        "time.sleep(60)\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", script])
    try:
        for _ in range(100):
            if child_pid.exists() and child_pid.read_text():
                break
            time.sleep(0.05)
        child = psutil.Process(int(child_pid.read_text()))
        launcher = Launcher(ProcessRegistry(tmp_path))
        launcher.stop("r1", {"pid": parent.pid, "source": "cli"})
        for thread in launcher._threads:
            thread.join(timeout=10)
        parent.wait(timeout=5)
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
    finally:
        for pid in (parent.pid, int(child_pid.read_text() or 0) if child_pid.exists() else 0):
            try:
                if pid:
                    psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                pass


def test_sse_frames_are_well_formed():
    from tyche.web.server import sse_lines

    async def items():
        yield {"event": "summary", "data": '{"a": 1}'}
        yield {"event": "ping", "data": "line one\nline two"}
        yield {"event": "event", "data": json.dumps({"text": "a\u2028b\u0085c"}, ensure_ascii=False)}

    async def collect():
        return [frame async for frame in sse_lines(items())]

    frames = asyncio.run(collect())
    assert frames[2] == 'event: event\ndata: {"text": "a\u2028b\u0085c"}\n\n'
    assert frames[:2] == [
        'event: summary\ndata: {"a": 1}\n\n',
        "event: ping\ndata: line one\ndata: line two\n\n",
    ]


def test_remote_binding_requires_the_launch_token(tmp_path):
    with pytest.raises(ValueError):
        create_app(tmp_path, static_dir=_MISSING_STATIC, host="0.0.0.0")
    app = create_app(tmp_path, static_dir=_MISSING_STATIC, launcher=FakeLauncher(), host="0.0.0.0", token="tok-123")
    client = TestClient(app, base_url="http://192.0.2.20:8765")
    assert client.get("/api/meta").status_code == 401
    assert client.get("/api/meta", params={"token": "wrong"}).status_code == 401
    hop = client.get("/", params={"token": "tok-123"}, follow_redirects=False)
    assert hop.status_code == 303 and "token=" not in hop.headers["location"]
    cookie = hop.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/meta").status_code == 200  # the cookie now authorizes the session
    other = TestClient(app, base_url="http://192.0.2.20:8765")
    assert other.get("/api/meta", headers={"Authorization": "Bearer tok-123"}).status_code == 200
    cross = client.post(
        "/api/runs", json={"topic": "A topic", "direction": "memory_engine"}, headers={"Origin": "http://evil.test"}
    )
    assert cross.status_code == 403


def test_ui_refuses_a_remote_host_without_opt_in(tmp_path, monkeypatch):
    from tyche.cli import _cmd_ui, build_parser
    from tyche.config import ConfigError

    served = {}
    monkeypatch.setattr("tyche.web.server.serve", lambda root, **kw: served.update(kw))
    args = build_parser().parse_args(["ui", "--workspace", str(tmp_path), "--host", "0.0.0.0", "--no-browser"])
    with pytest.raises(ConfigError, match="--allow-remote"):
        _cmd_ui(args)
    args = build_parser().parse_args(
        ["ui", "--workspace", str(tmp_path), "--host", "0.0.0.0", "--no-browser", "--allow-remote"]
    )
    _cmd_ui(args)
    assert served["host"] == "0.0.0.0" and len(served["token"]) >= 24
    _cmd_ui(build_parser().parse_args(["ui", "--workspace", str(tmp_path), "--no-browser"]))
    assert served["token"] is None


def test_readers_wait_for_a_line_that_is_still_being_written(tmp_path):
    from tyche.web import runs as web_runs

    ws = Workspace.create(tmp_path, "run-live", topic="t", direction="memory_engine", config_digest="x")
    run_dir = ws.run_dir
    events = run_dir / "events.jsonl"
    before = web_runs.event_line_count(run_dir)
    with events.open("a", encoding="utf-8") as handle:
        # A writer with ensure_ascii=False puts U+2028 in the line itself; it does not end the line.
        handle.write('{"kind": "note", "text": "a\u2028b"}\n{"kind": "stage.run')
    page = web_runs.events_page(run_dir, since=before)
    assert [e["kind"] for e in page["events"]] == ["note"] and page["next"] == before + 1
    assert page["events"][0]["text"] == "a b"
    with events.open("a", encoding="utf-8") as handle:
        handle.write('ning", "stage": "plan"}\n')
    later = web_runs.events_page(run_dir, since=page["next"])
    assert [e["kind"] for e in later["events"]] == ["stage.running"]
    with (run_dir / "provenance.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"id": "x", "name": "pl')
    with (run_dir / "usage.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"purpose": "plan", "sta')
    client = _client(tmp_path)
    assert client.get("/api/runs/run-live").status_code == 200
