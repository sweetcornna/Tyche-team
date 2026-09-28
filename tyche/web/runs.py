"""Read-side views over one Tyche workspace: run listing/detail derived from workspace files.

Every function here takes plain paths and dicts and returns plain dicts (JSON-ready), so they are
unit-testable against a ``tmp_path`` workspace without a server or a running pipeline. Process
liveness is never decided here: callers (``tyche.web.server``) pass in a ``process`` dict already
resolved by ``tyche.web.processes``.

Reads only. Writes UI metadata (title override, pinned, archived) to
``<workspace>/.tyche-web/runs.json``, which lives outside every run directory.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tyche import STAGES
from tyche.trace.lineage import read_provenance
from tyche.workspace import complete_lines, read_json, read_jsonl, write_json_atomic

UI_META_PATH = Path(".tyche-web") / "runs.json"
_TRASH_DIR = ".tyche-web/trash"
_PATH_FIELDS = ("dir", "pdf", "path", "evolutions_json", "design_path", "code_dir")


# -- small path/time helpers ---------------------------------------------


def _iso_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def runs_root(workspace_root: Path) -> Path:
    return workspace_root / "runs"


def run_dir_of(workspace_root: Path, run_id: str) -> Path:
    return runs_root(workspace_root) / run_id


def list_run_ids(workspace_root: Path) -> list[str]:
    root = runs_root(workspace_root)
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if child.name == ".tyche-web" or not child.is_dir():
            continue
        if (child / "state.json").exists():
            out.append(child.name)
    return out


# -- UI metadata (pinned/archived/title override) -------------------------


def load_ui_meta(workspace_root: Path) -> dict[str, dict[str, Any]]:
    data = read_json(workspace_root / UI_META_PATH, {})
    return data if isinstance(data, dict) else {}


def save_ui_meta(workspace_root: Path, meta: dict[str, dict[str, Any]]) -> None:
    write_json_atomic(workspace_root / UI_META_PATH, meta)


def update_ui_meta(workspace_root: Path, run_id: str, **values: Any) -> dict[str, Any]:
    meta = load_ui_meta(workspace_root)
    row = dict(meta.get(run_id) or {})
    for key, value in values.items():
        if value is None and key == "title":
            row.pop("title", None)
            continue
        if value is None:
            continue
        row[key] = value
    meta[run_id] = row
    save_ui_meta(workspace_root, meta)
    return row


def drop_ui_meta(workspace_root: Path, run_id: str) -> None:
    meta = load_ui_meta(workspace_root)
    if meta.pop(run_id, None) is not None:
        save_ui_meta(workspace_root, meta)


# -- provenance -------------------------------------------------------------


def _provenance(run_dir: Path) -> list[dict[str, Any]]:
    return read_provenance(run_dir)


def latest_artifact(run_dir: Path, name: str) -> dict[str, Any] | None:
    found = [rec for rec in _provenance(run_dir) if rec.get("name") == name]
    return max(found, key=lambda rec: rec.get("version", 0)) if found else None


def latest_artifact_path(run_dir: Path, name: str) -> Path | None:
    rec = latest_artifact(run_dir, name)
    if rec is None:
        return None
    path = run_dir / rec["path"]
    return path if path.exists() else None


def load_latest_json(run_dir: Path, name: str) -> Any | None:
    path = latest_artifact_path(run_dir, name)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_latest_text(run_dir: Path, name: str) -> str | None:
    path = latest_artifact_path(run_dir, name)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# -- title / status -----------------------------------------------------


def title_for(state: dict[str, Any], meta: dict[str, Any]) -> str:
    override = str(meta.get("title") or "").strip()
    if override:
        return override
    stages = state.get("stages", {})
    write_title = str(stages.get("write", {}).get("title") or "").strip()
    if write_title:
        return write_title
    plan_title = str(stages.get("plan", {}).get("title") or "").strip()
    if plan_title:
        return plan_title
    return str(state.get("topic") or state.get("run_id") or "")


def _stage_status(state: dict[str, Any], stage: str) -> str:
    return str(state.get("stages", {}).get(stage, {}).get("status", "pending"))


def stages_done_total(state: dict[str, Any]) -> tuple[int, int]:
    done = sum(1 for s in STAGES if _stage_status(state, s) == "done")
    return done, len(STAGES)


def current_stage(state: dict[str, Any]) -> str | None:
    for stage in STAGES:
        status = _stage_status(state, stage)
        if status == "running":
            return stage
    for stage in STAGES:
        if _stage_status(state, stage) == "failed":
            return stage
    for stage in STAGES:
        if _stage_status(state, stage) == "pending":
            return stage
    return "package"


def run_status(state: dict[str, Any], process: dict[str, Any] | None) -> str:
    if process is not None:
        return "running"
    statuses = [_stage_status(state, s) for s in STAGES]
    if statuses and all(s == "done" for s in statuses):
        return "done"
    if any(s == "failed" for s in statuses):
        return "failed"
    if any(s == "running" for s in statuses):
        # A stage claims to be running but nothing is alive: it was interrupted.
        return "stopped"
    if any(s == "done" for s in statuses) and any(s == "pending" for s in statuses):
        return "paused"
    return "pending"


def _package_pdf(run_dir: Path) -> tuple[Path | None, bool]:
    package = run_dir / "package"
    verified = package / "paper.pdf"
    if verified.exists():
        return verified, False
    unverified = package / "paper_UNVERIFIED.pdf"
    if unverified.exists():
        return unverified, True
    return None, False


def paper_info(run_id: str, run_dir: Path, state: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any] | None:
    pdf_path, unverified = _package_pdf(run_dir)
    source = "package"
    if pdf_path is None:
        rec = latest_artifact(run_dir, "paper_pdf")
        if rec is None:
            return None
        pdf_path = run_dir / rec["path"]
        if not pdf_path.exists():
            return None
        source = "review"
    gates = None
    package_gates = run_dir / "package" / "gates.json"
    if package_gates.exists():
        gates = read_json(package_gates)
    if gates is None:
        gates = load_latest_json(run_dir, "gates")
    main_pages = None
    if isinstance(gates, dict):
        main_pages = gates.get("stats", {}).get("main_pages")
    return {
        "url": f"/api/runs/{run_id}/files/paper.pdf",
        "thumb_url": f"/api/runs/{run_id}/files/paper-thumb.png",
        "source": source,
        "unverified": unverified,
        "main_pages": main_pages,
        "title": title_for(state, meta),
    }


def is_synthetic(state: dict[str, Any]) -> bool:
    exp = state.get("stages", {}).get("experiments", {})
    if exp.get("synthetic"):
        return True
    return exp.get("engine") == "fixture"


def method_of(state: dict[str, Any]) -> str | None:
    plan = state.get("stages", {}).get("plan", {})
    method = plan.get("method")
    return f"{method}" if method else None


# -- run summary / list -----------------------------------------------------


def run_summary(run_id: str, run_dir: Path, *, ui_meta: dict[str, Any] | None, process: dict[str, Any] | None) -> dict[str, Any]:
    state = read_json(run_dir / "state.json", {})
    meta = ui_meta or {}
    stages_done, stages_total = stages_done_total(state)
    updated_candidates = [_iso_mtime(run_dir / "state.json"), _iso_mtime(run_dir / "events.jsonl")]
    updated_at = max((c for c in updated_candidates if c), default=state.get("created_at"))
    paper = paper_info(run_id, run_dir, state, meta)
    return {
        "run_id": run_id,
        "title": title_for(state, meta),
        "topic": state.get("topic"),
        "direction": state.get("direction"),
        "created_at": state.get("created_at"),
        "updated_at": updated_at,
        "status": run_status(state, process),
        "stage": current_stage(state),
        "stages_done": stages_done,
        "stages_total": stages_total,
        "method": method_of(state),
        "synthetic": is_synthetic(state),
        "has_paper": paper is not None,
        "composite": state.get("stages", {}).get("review", {}).get("composite"),
        "unverified": bool(paper and paper.get("unverified")),
        "pinned": bool(meta.get("pinned")),
        "archived": bool(meta.get("archived")),
        "process": process,
    }


def list_runs(
    workspace_root: Path, *, archived: bool, process_lookup, ui_meta: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """``process_lookup(run_id) -> dict | None`` resolves live-process info per run."""
    meta_all = ui_meta if ui_meta is not None else load_ui_meta(workspace_root)
    rows = []
    for run_id in list_run_ids(workspace_root):
        row_meta = meta_all.get(run_id, {})
        if bool(row_meta.get("archived")) != archived:
            continue
        summary = run_summary(run_id, run_dir_of(workspace_root, run_id), ui_meta=row_meta, process=process_lookup(run_id))
        rows.append(summary)
    rows.sort(key=lambda r: (not r["pinned"], r["updated_at"] or ""), reverse=False)
    # Pinned first, then updated_at desc within each group.
    pinned = sorted([r for r in rows if r["pinned"]], key=lambda r: r["updated_at"] or "", reverse=True)
    rest = sorted([r for r in rows if not r["pinned"]], key=lambda r: r["updated_at"] or "", reverse=True)
    return pinned + rest


# -- run detail: stages ------------------------------------------------------


_ROW_META_KEYS = {"status", "error"}


def _stage_error_from_events(run_dir: Path, stage: str) -> str | None:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return None
    found = None
    for ev in read_jsonl(path):
        if ev.get("kind") == "stage.failed" and ev.get("stage") == stage:
            found = ev.get("error") or ev.get("message")
    return found


def stage_rows(run_dir: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for stage in STAGES:
        row = dict(state.get("stages", {}).get(stage, {}))
        status = row.get("status", "pending")
        running_at = row.get("running_at")
        done_at = row.get("done_at")
        duration_s = None
        start = _parse_iso(running_at)
        end = _parse_iso(done_at) or _parse_iso(row.get("failed_at"))
        if start is not None and end is not None:
            duration_s = round((end - start).total_seconds(), 3)
        error = row.get("error") or (_stage_error_from_events(run_dir, stage) if status == "failed" else None)
        summary = {
            k: v
            for k, v in row.items()
            if k != "status" and not k.endswith("_at") and k != "error"
        }
        rows.append(
            {
                "name": stage,
                "status": status,
                "running_at": running_at,
                "done_at": done_at,
                "duration_s": duration_s,
                "summary": summary,
                "error": error,
            }
        )
    return rows


# -- usage --------------------------------------------------------------


def usage_summary(run_dir: Path) -> dict[str, Any] | None:
    """Reuse ``tyche.llm.UsageMeter``/``UsageRecord`` over ``usage.jsonl``, plus a by-model split."""
    path = run_dir / "usage.jsonl"
    if not path.exists():
        return None
    from tyche.llm import UsageMeter, UsageRecord

    meter = UsageMeter()
    fields = set(UsageRecord.__dataclass_fields__)
    for row in read_jsonl(path):
        try:
            meter.records.append(UsageRecord(**{k: v for k, v in row.items() if k in fields}))
        except TypeError:
            continue
    summary = meter.summary()
    by_model: dict[str, dict[str, int]] = {}
    for rec in meter.records:
        row = by_model.setdefault(rec.model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        row["calls"] += 1
        row["input_tokens"] += rec.input_tokens
        row["output_tokens"] += rec.output_tokens
    summary["by_model"] = by_model
    return summary


# -- run detail ---------------------------------------------------------


def run_config(run_dir: Path) -> dict[str, Any] | None:
    """The saved resolved config for one run, rebuilt into role dicts that hold no secrets."""
    path = run_dir / "config.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    from tyche.config import ConfigError, TycheConfig

    roles: dict[str, Any] = {}
    try:
        cfg = TycheConfig(data)
        for role in ("writer", "reviewer", "experiments", "subject"):
            roles[role] = cfg.model(role).public_dict()
    except ConfigError:
        pass
    return {
        "engine": data.get("experiments", {}).get("engine"),
        "review_max_rounds": data.get("review", {}).get("max_rounds"),
        "max_main_pages": data.get("paper", {}).get("max_main_pages"),
        "roles": roles,
    }


def review_detail(run_dir: Path) -> dict[str, Any] | None:
    rounds = load_latest_json(run_dir, "review_rounds")
    if rounds is None:
        return None
    scores = load_latest_json(run_dir, "review_scores") or {}
    return {"rounds": rounds, "reviews": scores.get("reviews", {}), "stop_reason": None}


def summary_with_stages(
    run_id: str, run_dir: Path, *, ui_meta: dict[str, Any] | None, process: dict[str, Any] | None
) -> dict[str, Any]:
    """RunSummary plus the same ``stages`` list used in the detail response (for the SSE stream)."""
    state = read_json(run_dir / "state.json", {})
    return run_summary(run_id, run_dir, ui_meta=ui_meta, process=process) | {"stages": stage_rows(run_dir, state)}


def run_detail(run_id: str, run_dir: Path, *, ui_meta: dict[str, Any] | None, process: dict[str, Any] | None) -> dict[str, Any]:
    state = read_json(run_dir / "state.json", {})
    meta = ui_meta or {}
    summary = run_summary(run_id, run_dir, ui_meta=meta, process=process)
    notes = load_latest_text(run_dir, "operator_notes")
    return summary | {
        "stages": stage_rows(run_dir, state),
        "config": run_config(run_dir),
        "plan": load_latest_json(run_dir, "plan"),
        "notes": notes,
        "usage": usage_summary(run_dir),
        "review": review_detail(run_dir),
        "gates": load_latest_json(run_dir, "gates"),
        "paper": paper_info(run_id, run_dir, state, meta),
    }


# -- events ---------------------------------------------------------------


def _relativize(value: Any, run_dir: Path) -> Any:
    if not isinstance(value, str) or not value:
        return value
    p = Path(value)
    if not p.is_absolute():
        return value
    try:
        return p.relative_to(run_dir).as_posix()
    except ValueError:
        return p.name


def _strip_event_paths(event: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {k: (_relativize(v, run_dir) if k in _PATH_FIELDS else v) for k, v in event.items()}


def events_page(run_dir: Path, *, since: int = 0, limit: int = 500) -> dict[str, Any]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return {"events": [], "next": since}
    # Only complete lines get a sequence number, so a line still being written is sent next time.
    lines = complete_lines(path)
    end = min(len(lines), since + max(0, limit))
    events = []
    for seq in range(max(0, since), end):
        line = lines[seq]
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append({"seq": seq, **_strip_event_paths(row, run_dir)})
    return {"events": events, "next": end}


def event_line_count(run_dir: Path) -> int:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return 0
    return len(complete_lines(path))


# -- references -----------------------------------------------------------


def _cited_keys(run_dir: Path) -> set[str]:
    """Keys that appear in \\cite*{...} of the latest paper source, else the latest draft."""
    tex_texts: list[str] = []
    package_source = run_dir / "package" / "paper_source"
    if package_source.is_dir():
        tex_texts.extend(p.read_text(encoding="utf-8", errors="ignore") for p in package_source.glob("**/*.tex"))
    else:
        rec = latest_artifact(run_dir, "paper_source")
        if rec is not None:
            source_dir = run_dir / rec["path"]
            if source_dir.is_dir():
                tex_texts.extend(p.read_text(encoding="utf-8", errors="ignore") for p in source_dir.glob("**/*.tex"))
    keys: set[str] = set()
    if tex_texts:
        import re

        for text in tex_texts:
            for match in re.finditer(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])?\{([^}]*)\}", text):
                keys.update(part.strip() for part in match.group(1).split(","))
        return {k for k in keys if k}
    draft = load_latest_json(run_dir, "draft")
    if isinstance(draft, dict):
        import re

        for text in (draft.get("sections") or {}).values():
            for match in re.finditer(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])?\{([^}]*)\}", str(text)):
                keys.update(part.strip() for part in match.group(1).split(","))
    return keys


def references_detail(run_dir: Path) -> dict[str, Any] | None:
    manifest = load_latest_json(run_dir, "source_manifest")
    if manifest is None:
        return None
    cited = _cited_keys(run_dir)
    cards_by_key: dict[str, list[dict[str, Any]]] = {}
    for card in manifest.get("evidence_cards", []):
        cards_by_key.setdefault(card.get("key"), []).append(card)
    papers = []
    for paper in manifest.get("papers", []):
        key = paper.get("key")
        papers.append({**paper, "cited": key in cited, "cards": cards_by_key.get(key, [])})
    return {
        "papers": papers,
        "excluded": manifest.get("excluded", []),
        "stats": manifest.get("stats", {}),
        "synthesis": manifest.get("synthesis", {}),
    }


# -- experiments ------------------------------------------------------------


_STATUS_MAP = {"done": "completed", "running": "running", "failed": "failed"}


def _attempt_dirs(run_dir: Path) -> list[Path]:
    root = run_dir / "experiments" / "engine" / "experiments"
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)


# Public aliases for the SSE stream (tyche.web.server), which needs the same attempt/manager-event
# reads incrementally rather than through the one-shot ``experiments_detail``.
attempt_dirs = _attempt_dirs


def manager_events(attempt_dir: Path) -> list[dict[str, Any]]:
    return _manager_events(attempt_dir)


def _manager_events(attempt_dir: Path) -> list[dict[str, Any]]:
    path = attempt_dir / "manager" / "events.jsonl"
    if not path.exists():
        return []
    return read_jsonl(path)


def _attempt_terminal(attempt_dir: Path) -> bool:
    state = read_json(attempt_dir / "manager" / "state.json", {})
    return bool(isinstance(state, dict) and state.get("terminal"))


def _newest_trace(attempt_dir: Path) -> Path | None:
    modules_dir = attempt_dir / "modules"
    if not modules_dir.is_dir():
        return None
    traces = list(modules_dir.glob("*/round_*/agent_trace.jsonl"))
    if not traces:
        return None
    return max(traces, key=lambda p: p.stat().st_mtime)


def _trace_events(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def _open_subagent(attempt_dir: Path) -> dict[str, Any] | None:
    """The manager's latest ``subagent_start`` that has no matching ``subagent_finish`` yet."""
    open_start = None
    for event in _manager_events(attempt_dir):
        kind = event.get("event")
        if kind == "subagent_start":
            open_start = event
        elif kind == "subagent_finish" and open_start is not None:
            if (event.get("module"), event.get("round")) == (open_start.get("module"), open_start.get("round")):
                open_start = None
    return open_start


def _live_from_attempt(attempt_dir: Path) -> dict[str, Any] | None:
    # The manager keeps its own agent trace too; while a sub-agent (design, coding, execution,
    # reflection) runs, report that sub-agent and its trace rather than the manager's.
    start = _open_subagent(attempt_dir)
    if start is not None and start.get("module"):
        round_no = start.get("round")
        pattern = f"round_{int(round_no):03d}_*/agent_trace.jsonl" if isinstance(round_no, int) else "round_*/agent_trace.jsonl"
        traces = sorted((attempt_dir / "modules" / str(start["module"])).glob(pattern))
        events = _trace_events(traces[-1]) if traces else []  # execution runs code and may have no agent trace
        return {
            "attempt": attempt_dir.name,
            "module": start["module"],
            "round": round_no,
            "model_calls": sum(1 for e in events if e.get("event") == "model_call_start"),
            "since": start.get("ts"),
            "last_event_at": (events[-1].get("ts") if events else start.get("ts")),
        }
    trace = _newest_trace(attempt_dir)
    if trace is None:
        return None
    events = _trace_events(trace)
    if not events:
        return None
    parts = trace.relative_to(attempt_dir / "modules").parts  # <module>/round_NNN_attempt_NNN/agent_trace.jsonl
    module = parts[0] if parts else None
    round_match = None
    if len(parts) > 1:
        import re

        m = re.match(r"round_(\d+)_attempt_(\d+)", parts[1])
        if m:
            round_match = int(m.group(1))
    model_calls = sum(1 for e in events if e.get("event") == "model_call_start")
    since = events[0].get("ts")
    last_event_at = events[-1].get("ts")
    return {
        "attempt": attempt_dir.name,
        "module": module,
        "round": round_match,
        "model_calls": model_calls,
        "since": since,
        "last_event_at": last_event_at,
    }


def _experiment_status(state: dict[str, Any]) -> str:
    status = state.get("stages", {}).get("experiments", {}).get("status", "pending")
    return _STATUS_MAP.get(status, "pending")


def _design_md(run_dir: Path, attempts: list[Path]) -> str | None:
    text = load_latest_text(run_dir, "experiment_design")
    if text is not None:
        return text
    for attempt_dir in reversed(attempts):
        design = attempt_dir / "design" / "experiment_design.md"
        if design.exists():
            try:
                return design.read_text(encoding="utf-8")
            except OSError:
                continue
    return None


def _metrics_dict(run_dir: Path, attempts: list[Path]) -> dict[str, dict[str, float]]:
    from tyche.experiments import numeric_metrics, read_metrics_dir

    metrics_dir = latest_artifact_path(run_dir, "experiment_results")
    if metrics_dir is None or not metrics_dir.is_dir():
        metrics_dir = attempts[-1] / "results" if attempts and (attempts[-1] / "results").is_dir() else None
    if metrics_dir is None:
        return {}
    variants = read_metrics_dir(metrics_dir)
    return {name: numeric_metrics(data) for name, data in variants.items()}


def _files_listing(run_dir: Path, attempts: list[Path]) -> tuple[list[dict[str, Any]], str | None]:
    code_dir = latest_artifact_path(run_dir, "experiment_code")
    files_root = "artifact"
    if code_dir is None or not code_dir.is_dir():
        code_dir = attempts[-1] / "agent_workspace" / "output" if attempts else None
        files_root = "live"
        if code_dir is None or not code_dir.is_dir():
            return [], None
    files = []
    for path in sorted(code_dir.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 2 * 1024 * 1024:
            continue
        files.append({"path": path.relative_to(code_dir).as_posix(), "size": size})
        if len(files) >= 500:
            break
    return files, files_root


def experiment_files_root(run_dir: Path) -> Path | None:
    code_dir = latest_artifact_path(run_dir, "experiment_code")
    if code_dir is not None and code_dir.is_dir():
        return code_dir
    attempts = _attempt_dirs(run_dir)
    if not attempts:
        return None
    out = attempts[-1] / "agent_workspace" / "output"
    return out if out.is_dir() else None


def _reflections(run_dir: Path, attempts: list[Path]) -> list[dict[str, str]]:
    rec = latest_artifact(run_dir, "reflection")
    if rec is not None:
        path = run_dir / rec["path"]
        if path.exists():
            return [{"name": path.name, "text": path.read_text(encoding="utf-8", errors="ignore")}]
    if attempts:
        rev_dir = attempts[-1] / "agent_workspace" / "output"
        out = []
        if rev_dir.is_dir():
            for path in sorted(rev_dir.glob("revision-*.md")):
                out.append({"name": path.name, "text": path.read_text(encoding="utf-8", errors="ignore")})
        return out
    return []


def experiments_detail(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    exp_state = state.get("stages", {}).get("experiments", {})
    outcome = load_latest_json(run_dir, "experiments") or {}
    attempts = _attempt_dirs(run_dir)
    timeline = []
    for attempt_dir in attempts:
        for ev in _manager_events(attempt_dir):
            timeline.append(
                {
                    "attempt": attempt_dir.name,
                    "ts": ev.get("ts"),
                    "event": ev.get("event"),
                    "module": ev.get("module"),
                    "round": ev.get("round"),
                    "outcome": ev.get("outcome"),
                }
            )
    timeline.sort(key=lambda e: e.get("ts") or "")
    live = None
    for attempt_dir in reversed(attempts):
        if not _attempt_terminal(attempt_dir):
            live = _live_from_attempt(attempt_dir)
            break
    files, files_root = _files_listing(run_dir, attempts)
    return {
        "engine": outcome.get("engine") or exp_state.get("engine"),
        "status": _experiment_status(state),
        "synthetic": bool(outcome.get("synthetic", exp_state.get("synthetic", False))),
        "variants": sorted(exp_state.get("variants") or outcome.get("variants") or []),
        "notes": outcome.get("notes", ""),
        "design_md": _design_md(run_dir, attempts),
        "attempts": [p.name for p in attempts],
        "timeline": timeline,
        "live": live,
        "metrics": _metrics_dict(run_dir, attempts),
        "files": files,
        "files_root": files_root,
        "reflections": _reflections(run_dir, attempts),
    }


# -- analysis / ledger / report / log ---------------------------------------


def analysis_detail(run_id: str, run_dir: Path) -> dict[str, Any] | None:
    analysis = load_latest_json(run_dir, "analysis")
    if analysis is None:
        return None
    out = dict(analysis)
    if latest_artifact(run_dir, "fig_results") is not None:
        out["figure_url"] = f"/api/runs/{run_id}/files/figure.png"
    return out


def ledger_detail(run_dir: Path) -> dict[str, Any] | None:
    return load_latest_json(run_dir, "ledger")


def report_text(run_dir: Path) -> str | None:
    path = run_dir / "package" / "run_report.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


# -- agent sessions ------------------------------------------------------------

AGENT_STAGES = ("plan", "write", "review")
_CALL_BLOCK = re.compile(r"<call\s+(?:tool|name)\s*=\s*[\"'][\w.:-]+[\"']\s*(?:/>|>.*?</call>)", re.S)
# Chat-template markers some models leak into plain replies (channel tags, instruction brackets);
# they are dropped from the displayed prose only; the transcript keeps the reply as sent.
_TEMPLATE_MARKERS = re.compile(r"</?(?:commentary|analysis|final)\b>?|\[/?INST\]|<\|[a-z_]+\|>")


def _transcript_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in complete_lines(path):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n... ({len(text) - limit} more characters)"


def _session_details(run_dir: Path, stage: str, rows: list[dict[str, Any]], *, live: bool) -> dict[str, Any]:
    task_index = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].get("kind") == "task"), 0)
    task = rows[task_index] if rows else {}
    current = rows[task_index:]
    outcome = next((r for r in reversed(current) if r.get("kind") == "outcome"), None)
    last = rows[-1] if rows else {}
    if outcome:
        status = outcome.get("status", "unknown")
    elif last.get("kind") == "assistant" and not last.get("calls") and not last.get("error"):
        status = "done"
    elif last.get("kind") == "result" and last.get("ok") and last.get("tool") in {"submit", "submit_plan"}:
        status = "done"
    else:
        stage_state = read_json(run_dir / "state.json", {}).get("stages", {}).get(stage, {})
        status = "running" if live and stage_state.get("status") == "running" else "interrupted"
    if status == "running":
        waiting = any(r.get("kind") == "assistant" and "delegate" in (r.get("calls") or []) for r in current[-2:])
        if waiting:
            status = "delegating"
    return {
        "status": status,
        "model": task.get("model"),
        "provider": task.get("provider"),
        "role": task.get("role"),
        "parent_session": task.get("parent_session"),
        "last_activity": last.get("at"),
    }


def agent_sessions(run_dir: Path, *, live: bool = False) -> dict[str, Any]:
    """One summary per agent session transcript of a run (plan, write, and review stages)."""
    sessions = []
    for stage in AGENT_STAGES:
        folder = run_dir / stage / "agents" / "transcripts"
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
            rows = _transcript_rows(path)
            if not rows:
                continue
            results = [r for r in rows if r.get("kind") == "result"]
            sessions.append(
                {
                    "stage": stage,
                    "name": path.stem,
                    "session": rows[0].get("session", path.stem),
                    "tasks": sum(1 for r in rows if r.get("kind") == "task"),
                    "turns": sum(1 for r in rows if r.get("kind") == "assistant"),
                    "tool_calls": len(results),
                    "tool_errors": sum(1 for r in results if not r.get("ok")),
                    "handbacks": sum(1 for r in rows if r.get("kind") == "stop_blocked"),
                    "compactions": sum(1 for r in rows if r.get("kind") == "compact"),
                    "started": rows[0].get("at"),
                    "ended": rows[-1].get("at"),
                    **_session_details(run_dir, stage, rows, live=live),
                }
            )
    return {"sessions": sessions}


def agent_transcript(
    run_dir: Path, stage: str, name: str, *, max_text: int = 20000, live: bool = False
) -> dict[str, Any] | None:
    """A session's transcript as display items: tasks, the agent's prose with each call and its result,
    operator messages, hand-backs, and compactions. ``waiting_since`` is when the session last sent the
    model a message it has not answered yet (None once it has finished)."""
    from tyche.agent.tools import ProtocolError, parse_calls

    if stage not in AGENT_STAGES or not re.fullmatch(r"[\w.-]+", name):
        return None
    path = run_dir / stage / "agents" / "transcripts" / f"{name}.jsonl"
    if not path.is_file():
        return None
    items: list[dict[str, Any]] = []
    # Calls of the latest reply still waiting for their result rows, in the order they ran.
    waiting: list[dict[str, Any]] = []
    rows = _transcript_rows(path)
    for row in rows:
        kind = row.get("kind")
        if kind in {"outcome", "turn_start"}:
            continue
        if kind == "result":
            result = {"ok": bool(row.get("ok")), "text": _clip(row.get("text", ""), max_text)}
            if waiting and waiting[0]["tool"] == row.get("tool"):
                waiting.pop(0)["result"] = result
                continue
            items.append({"kind": "result", "at": row.get("at"), "turn": row.get("turn"), "tool": row.get("tool"), **result})
            continue
        item: dict[str, Any] = {"kind": kind, "at": row.get("at"), "turn": row.get("turn")}
        if kind == "assistant":
            text = row.get("text", "")
            try:
                calls = parse_calls(text)
            except ProtocolError:
                calls = []
            item["prose"] = _clip(_TEMPLATE_MARKERS.sub("", _CALL_BLOCK.sub("", text)).strip(), max_text)
            item["error"] = row.get("error")
            item["calls"] = []
            seen: dict[str, int] = {}
            for c in calls:
                entry: dict[str, Any] = {
                    "tool": c.tool,
                    "args": {k: _clip(v, max_text) for k, v in c.raw_args.items()},
                    "result": None,
                }
                key = json.dumps([c.tool, c.raw_args], sort_keys=True)
                if key in seen:
                    # The session runs a call repeated within one reply only once.
                    entry["duplicate_of"] = seen[key]
                else:
                    seen[key] = c.index
                item["calls"].append(entry)
            waiting = [e for e in item["calls"] if "duplicate_of" not in e]
        elif kind == "stop_blocked":
            item["text"] = _clip(row.get("reason", ""), max_text)
        elif kind == "compact":
            item.update(text=_clip(row.get("summary", ""), max_text), tokens_before=row.get("tokens_before"))
        else:
            item["text"] = _clip(row.get("text", ""), max_text)
        items.append(item)
    last = rows[-1] if rows else {}
    details = _session_details(run_dir, stage, rows, live=live)
    waiting_since = last.get("at") if details["status"] == "running" else None
    return {"stage": stage, "name": name, "items": items, "waiting_since": waiting_since, **details}


def log_tail(workspace_root: Path, run_id: str, *, tail: int = 400) -> dict[str, Any]:
    path = workspace_root / ".tyche-web" / "logs" / f"{run_id}.log"
    if not path.exists():
        return {"lines": [], "path": None}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return {"lines": lines[-tail:], "path": f".tyche-web/logs/{run_id}.log"}


# -- artifacts ---------------------------------------------------------------


_KIND_BY_SUFFIX = {".json": "json", ".md": "md", ".bib": "bib", ".tex": "tex", ".pdf": "pdf"}


def _artifact_kind(path_str: str) -> str:
    suffix = Path(path_str).suffix
    if not suffix:
        return "dir"
    return _KIND_BY_SUFFIX.get(suffix, "other")


def artifacts_listing(run_dir: Path) -> dict[str, Any]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for rec in _provenance(run_dir):
        by_name.setdefault(rec["name"], []).append(rec)
    artifacts = []
    for name, recs in sorted(by_name.items()):
        recs = sorted(recs, key=lambda r: r.get("version", 0))
        versions = []
        for rec in recs:
            target = run_dir / rec["path"]
            try:
                size = target.stat().st_size if target.is_file() else 0
            except OSError:
                size = 0
            versions.append(
                {
                    "version": rec["version"],
                    "id": rec["id"],
                    "stage": rec.get("stage"),
                    "sha256": rec.get("sha256"),
                    "path": rec["path"],
                    "size": size,
                    "created_at": rec.get("created_at"),
                }
            )
        artifacts.append({"name": name, "kind": _artifact_kind(recs[-1]["path"]), "versions": versions})
    return {"artifacts": artifacts}


def artifact_record(run_dir: Path, name: str, version: int) -> dict[str, Any] | None:
    for rec in _provenance(run_dir):
        if rec.get("name") == name and rec.get("version") == version:
            return rec
    return None


# -- library / lessons --------------------------------------------------


def library_papers(workspace_root: Path) -> list[dict[str, Any]]:
    meta_all = load_ui_meta(workspace_root)
    out = []
    for run_id in list_run_ids(workspace_root):
        row_meta = meta_all.get(run_id, {})
        if bool(row_meta.get("archived")):
            continue
        run_dir = run_dir_of(workspace_root, run_id)
        state = read_json(run_dir / "state.json", {})
        paper = paper_info(run_id, run_dir, state, row_meta)
        if paper is None:
            continue
        updated_at = max(
            (c for c in (_iso_mtime(run_dir / "state.json"), _iso_mtime(run_dir / "events.jsonl")) if c),
            default=state.get("created_at"),
        )
        gates = load_latest_json(run_dir, "gates") or {}
        package_gates = read_json(run_dir / "package" / "gates.json")
        if isinstance(package_gates, dict):
            gates = package_gates
        out.append(
            {
                "run_id": run_id,
                "title": paper["title"],
                "direction": state.get("direction"),
                "created_at": state.get("created_at"),
                "updated_at": updated_at,
                "composite": state.get("stages", {}).get("review", {}).get("composite"),
                "main_pages": paper.get("main_pages"),
                "unverified": paper.get("unverified", False),
                "synthetic": is_synthetic(state),
                "gates_passed": bool(gates.get("passed")) if isinstance(gates, dict) else None,
                "pdf_url": paper["url"],
                "thumb_url": paper["thumb_url"],
            }
        )
    out.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    return out


def lessons_list(workspace_root: Path) -> list[dict[str, Any]]:
    """Cross-run lessons, the way ``tyche lessons`` reads them.

    Fields: id, status, category, guidance (the lesson body), sections, runs (support run ids),
    helped, misses, created_at, updated_at. ``updated_at`` is not tracked separately by the memory
    store, so it is reported equal to ``created_at`` (see the module docstring / task report for
    this as a documented simplification).
    """
    db = workspace_root / "memory.db"
    if not db.exists():
        return []
    from tyche.memory import MemoryStore

    store = MemoryStore(db)
    try:
        items = store.list(kinds=["lesson"], scopes=["global"])
    finally:
        store.close()
    out = []
    for item in items:
        meta = item.meta
        out.append(
            {
                "id": item.id,
                "status": meta.get("status", "candidate"),
                "category": meta.get("category", ""),
                "guidance": item.body,
                "sections": meta.get("sections", []),
                "runs": meta.get("support_runs", []),
                "helped": meta.get("helped", 0),
                "misses": meta.get("misses", 0),
                "created_at": item.created_at,
                "updated_at": item.created_at,
            }
        )
    return out


# -- trash ----------------------------------------------------------------


def trash_run(workspace_root: Path, run_id: str) -> str:
    from datetime import datetime as _dt

    run_dir = run_dir_of(workspace_root, run_id)
    trash_dir = workspace_root / _TRASH_DIR
    trash_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target = trash_dir / f"{run_id}-{stamp}"
    run_dir.rename(target)
    drop_ui_meta(workspace_root, run_id)
    return str(Path(_TRASH_DIR) / target.name)
