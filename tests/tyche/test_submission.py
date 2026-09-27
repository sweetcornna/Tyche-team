import json

from tyche.experiments.bridge import agent_usage_totals, collect_agent_traces, openjiuwen_usage
from tyche.submission import (
    REDACTED,
    module_of,
    redacted_copy,
    resource_report,
    run_config_yaml,
    scan_bundle,
    secret_values,
    stage_times,
)

from .conftest import needs_latex
from .test_pipeline import _pipeline


def _trace(path, *events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _attempt(tmp_path, name="tyche-r-a1"):
    attempt = tmp_path / name
    _trace(
        attempt / "modules" / "manager" / "round_001_attempt_001" / "agent_trace.jsonl",
        {"event": "trace_start"},
        {"event": "model_call_start"},
        {"event": "model_call_end", "call_id": "m1", "usage": {"input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 60}},
        {"event": "model_call_end", "call_id": "m2", "usage": {}},
        {"event": "model_call_error", "call_id": "m3"},
        {"event": "model_call_end", "call_id": None, "usage": {}},  # the rail's closing record of the failed call
    )
    _trace(
        attempt / "modules" / "code_implementation" / "round_002_attempt_001" / "agent_trace.jsonl",
        {"event": "model_call_end", "call_id": "m1",
         "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_cache_hit_tokens": 900}},
    )
    (attempt / "modules" / "code_implementation" / "round_002_attempt_001" / "run.py").write_text("print(1)\n")
    return attempt


def test_openjiuwen_usage_is_read_from_the_agents_own_traces(tmp_path):
    attempt = _attempt(tmp_path)
    usage = openjiuwen_usage(attempt)
    assert usage["attempt"] == "tyche-r-a1"
    assert usage["modules"]["manager"] == {
        "calls": 2, "calls_without_usage": 1, "failed_calls": 1, "input_tokens": 100, "cached_tokens": 60, "output_tokens": 10,
    }
    assert usage["modules"]["code_implementation"]["input_tokens"] == 1000
    assert usage["modules"]["code_implementation"]["cached_tokens"] == 900

    # A resumed attempt's later record replaces its earlier one; other attempts add up.
    earlier = {"attempt": "tyche-r-a1", "modules": {"manager": {"calls": 1, "input_tokens": 5}}}
    other = {"attempt": "tyche-r-a2", "modules": {"manager": {"calls": 3, "input_tokens": 7}}}
    totals = agent_usage_totals([earlier, other, usage])
    assert totals["attempts"] == 2 and totals["calls"] == 6 and totals["input_tokens"] == 1107

    copied = tmp_path / "copy"
    assert collect_agent_traces(attempt, copied) == 2  # traces only, not the generated code
    assert openjiuwen_usage(copied / "tyche-r-a1") == usage


def test_experiment_stage_keeps_agent_traces_and_usage(tmp_path, workspace):
    attempt = _attempt(tmp_path)
    pipe = _pipeline(tmp_path, workspace)
    assert pipe.agent_usage() is None
    pipe._save_agent_usage(attempt, workspace.stage_dir("experiments") / "engine")
    traces = workspace.latest("experiment_traces")
    usage = workspace.latest("experiment_usage")
    assert traces is not None and usage is not None and usage.inputs == [traces.id]
    assert pipe.agent_usage()["calls"] == 3


def test_stage_times_count_failed_interrupted_and_open_attempts():
    def ev(at, kind, stage=None):
        return {"at": f"2026-09-27T{at}+00:00", "kind": kind, **({"stage": stage} if stage else {})}

    times = stage_times([
        ev("01:00:00", "stage.running", "plan"), ev("01:05:00", "stage.done", "plan"),
        ev("01:05:00", "stage.running", "review"), ev("01:20:00", "review.round"),  # the process then died
        ev("02:00:00", "stage.running", "review"), ev("02:10:00", "stage.failed", "review"),
        ev("02:30:00", "stage.running", "review"), ev("03:00:00", "stage.done", "review"),
        ev("03:00:00", "stage.running", "package"),
    ])
    assert times["plan"].seconds == 300 and times["plan"].attempts == 1
    review = times["review"]
    assert (review.attempts, review.failed, review.interrupted, review.lower_bound) == (3, 1, 1, True)
    assert review.seconds == (15 + 10 + 30) * 60
    assert times["package"].open and times["package"].seconds == 0


def test_usage_purposes_map_to_report_modules():
    assert module_of("review:auditor") == "忠实度审计"
    assert module_of("review:rigor") == "评审团（三位评审）"
    assert module_of("write:title") == module_of("write:method")
    assert module_of("custom:thing") == "custom"


def test_scan_refuses_credentials_and_reports_endpoint_mentions(tmp_path):
    root = tmp_path / "team"
    files = {
        "evidence/run/a.json": '{"note": "real-secret-value-123456"}',
        "evidence/run/b.txt": "a task-specific-retrieval-with-a-long-hyphenated-name",
        "evidence/run/c.json": '{"api_base": "https://gw.example.test/v1"}',
        "code/tests/t.py": 'SECRET = "sk-fixture-secret-0000abcdefgh"',
        "code/tyche/x.py": "real-secret-value-123456",
        "resource_report.md": "sk-" + "a" * 30,
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    leaks, mentions = scan_bundle(root, {"real-secret-value-123456"}, {"gw.example.test"})
    assert leaks == ["code/tyche/x.py", "evidence/run/a.json", "resource_report.md"]
    assert mentions == ["evidence/run/c.json"]


def test_secret_values_come_from_credential_variables_only(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENALEX_API_KEY='fixture-openalex-0000'\nMODEL_NAME=fixture-model-name-long\n", encoding="utf-8")
    env = {"API_KEY": "fixture-api-key-0000", "S2_API_KEY": "short", "API_BASE": "https://example.test/v1"}
    assert secret_values(env, [dotenv, tmp_path / "missing.env"]) == {"fixture-api-key-0000", "fixture-openalex-0000"}


@needs_latex
async def test_evidence_copy_hides_the_endpoint_and_still_verifies(tmp_path):
    from tyche.config import TycheConfig
    from tyche.selftest import run_selftest
    from tyche.trace.verify import report, verify_package

    summary = await run_selftest(root=tmp_path, echo=lambda *a: None)
    assert summary["ok"], summary
    package = tmp_path / "runs" / "selftest" / "package"

    target = tmp_path / "evidence"
    endpoints = redacted_copy(package, target)
    assert endpoints
    text = (target / "environment.json").read_text() + (target / "run_record" / "config.json").read_text()
    assert REDACTED in text and not any(e in text for e in endpoints)
    assert report(verify_package(target))["passed"]

    rendered = resource_report(target, team="Fixture team", commit="0" * 40)
    assert rendered.startswith("# 资源消耗报告") and "Fixture team" in rendered and "S0 规划" in rendered
    assert "没有找到 openJiuwen 实验智能体的调用记录" in rendered  # the fixture engine runs no agents

    # config.yaml reproduces the run's settings, with the endpoint read from the environment.
    config_file = tmp_path / "config.yaml"
    config_file.write_text(run_config_yaml(package, "selftest"), encoding="utf-8")
    loaded = TycheConfig.load(config_file, env={"API_BASE": "https://example.test/v1"})
    saved = json.loads((package / "run_record" / "config.json").read_text())
    for spec in saved["models"].values():
        if spec.get("api_base"):
            spec["api_base"] = "https://example.test/v1"
    assert loaded.data == saved
