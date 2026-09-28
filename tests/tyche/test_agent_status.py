"""The workbench must show actual models and terminal outcomes, including helper failures."""

import json

import pytest

from tyche.agent import AgentSession, Hooks, Subagent, Tool, delegate_tool
from tyche.agent.tools import ToolCall, bind_args
from tyche.llm import ScriptedLLM
from tyche.web.runs import agent_sessions, agent_transcript
from tyche.workspace import Workspace


def setup_run(tmp_path):
    ws = Workspace.create(tmp_path, "status-run", topic="test", direction="memory_engine", config_digest="x")
    ws.mark_stage("write", "running")
    transcript = ws.run_dir / "write" / "agents" / "transcripts" / "helper_01.jsonl"
    return ws, transcript


@pytest.mark.parametrize("status", ["done", "blocked", "max_turns"])
async def test_session_records_actual_model_and_terminal_status(tmp_path, status):
    ws, transcript = setup_run(tmp_path)
    reply = '<call tool="noop"/>' if status == "max_turns" else "Finished."
    session = AgentSession(
        ScriptedLLM({"agent:helper": lambda *_: reply}, name="selected-model"), name="helper", instructions="check",
        tools=[Tool("noop", "noop", lambda: "ok")], transcript=transcript, parent_session="author",
        max_turns=1, max_stop_blocks=0,
        hooks=Hooks(on_stop=[lambda _: "checks failed"] if status == "blocked" else []),
    )
    assert (await session.run("check evidence")).status == status
    summary = agent_sessions(ws.run_dir, live=True)["sessions"][0]
    assert summary["status"] == status
    assert summary["model"] == "selected-model"
    assert summary["parent_session"] == "author"
    view = agent_transcript(ws.run_dir, "write", "helper_01", live=True)
    assert view["waiting_since"] is None
    assert not {"outcome", "turn_start"} & {item["kind"] for item in view["items"]}


async def test_model_failure_records_failed_without_echoing_exception(tmp_path):
    ws, transcript = setup_run(tmp_path)

    def fail(*_):
        raise RuntimeError("credential-do-not-display")

    session = AgentSession(ScriptedLLM({"agent:helper": fail}), name="helper", instructions="check", tools=[], transcript=transcript)
    with pytest.raises(RuntimeError):
        await session.run("check")
    assert "credential-do-not-display" not in transcript.read_text()
    assert agent_sessions(ws.run_dir, live=True)["sessions"][0]["status"] == "failed"


def test_interrupted_run_is_not_shown_as_still_working_and_restart_uses_latest_task(tmp_path):
    ws, transcript = setup_run(tmp_path)
    transcript.parent.mkdir(parents=True)
    rows = [
        {"kind": "task", "session": "helper", "at": 1, "model": "old-model"},
        {"kind": "outcome", "status": "done", "at": 2},
        {"kind": "task", "session": "helper", "at": 3, "model": "new-model"},
        {"kind": "turn_start", "at": 4},
    ]
    transcript.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert agent_sessions(ws.run_dir)["sessions"][0]["status"] == "interrupted"
    assert agent_transcript(ws.run_dir, "write", "helper_01")["waiting_since"] is None
    view = agent_transcript(ws.run_dir, "write", "helper_01", live=True)
    assert view["status"] == "running" and view["waiting_since"] == 4
    assert view["model"] == "new-model"


async def test_incomplete_helper_returns_failed_tool_result():
    helper = Subagent("check", "check", lambda: AgentSession(
        ScriptedLLM({"agent:helper": lambda *_: '<call tool="noop"/>'}), name="helper", instructions="check",
        tools=[Tool("noop", "noop", lambda: "ok")], max_turns=1,
    ))
    tool = delegate_tool([helper])
    args = bind_args(tool, ToolCall("delegate", {"agent": "check", "task": "check"}).raw_args)
    result = await tool.invoke(args)
    assert not result.ok and "max_turns" in result.text
