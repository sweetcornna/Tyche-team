"""Competition submission bundle (CCF BDCI 2026, openJiuwen track).

Assembles the layout the organizers' submission sample prescribes from one verified paper
package:

    <team>/
      Agentic Reviewer/PaperReview-AccessToken.txt
      paper/paper.pdf
      code/        entry point, run configuration, pinned requirements, guide, Tyche source
      docs/        architecture, openJiuwen module calls, innovation
      evidence/<run-id>/   the package itself, model endpoint redacted
      resource_report.md   computed from the package's usage and event logs
      framework_contribution.md
      README.md, SHA256SUMS

Nothing here calls a model. The package must pass ``tyche verify`` before it is bundled and the
redacted copy must pass it again; every number in the resource report is read from the run
record, and the bundle is scanned for credentials before it is reported complete.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from tyche.workspace import read_jsonl

REDACTED = "<redacted>"
TOKEN_PLACEHOLDER = (
    "请在 https://paperreview.ai 以 ICLR 模板提交 paper/paper.pdf，把获得的 access token 粘贴到这里并删除本行。"
)

# Repository paths that make up Tyche (everything else in the repository is upstream JiuwenSwarm).
CODE_PATHS = (
    "tyche",
    "tests/__init__.py",
    "tests/tyche",
    "scripts/tyche",
    "jiuwenswarm/resources/agent/workspace/skills/tyche-iclr-paper",
    "jiuwenswarm/resources/agent/workspace/skills/tyche-paper",
    "LICENSE",
    "NOTICE.md",
)
SUBMISSION_DOCS = Path("docs/tyche/submission")
# Agent traces copied from the run directory for packages made before traces were packaged.
AGENT_TRACES = "openjiuwen_agent_traces"
TEMPLATES = Path("scripts/tyche/submission")

# Usage purposes grouped into the modules the report lists, most specific prefix first.
_MODULES = (
    # Agent sessions (tyche/agent), when agents.enabled; the one-call-per-step purposes follow.
    ("agent:plan", "规划智能体（回顾经验、检索、校验并提交计划）"),
    ("agent:author", "作者智能体（撰写、自检、按评审修订、编译修复）"),
    ("agent:fact_checker", "事实核查子智能体"),
    ("agent:review:auditor", "忠实度审计（带工具）"),
    ("agent:review", "评审团（三位评审，带工具）"),
    ("plan", "规划（研究计划）"),
    ("survey", "文献调研（检索式、筛选、证据卡、综述）"),
    ("write", "分节写作与标题"),
    ("review:auditor", "忠实度审计"),
    ("review", "评审团（三位评审）"),
    ("revise", "按评审发现定向修订"),
    ("shorten", "篇幅压缩"),
    ("repair", "LaTeX 编译修复"),
    ("evolve", "跨运行写作经验提炼"),
)
_AGENT_MODULES = {
    "manager": "实验编排（manager）",
    "experiment_design": "实验设计",
    "code_implementation": "代码实现与冒烟测试",
    "experiment_execution": "实验执行",
    "reflection": "结果反思与设计修订",
}
_STAGE_NAMES = {
    "plan": "S0 规划",
    "survey": "S1 文献调研",
    "experiments": "S2 实验（openJiuwen）",
    "analysis": "S3 统计分析",
    "write": "S4 写作",
    "review": "S5 评审与修订",
    "evolve": "S6 经验演进",
    "package": "S7 打包",
}
_SECRET_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_SECRET_ENV = re.compile(r"(API_KEY|_TOKEN|_SECRET|PASSWORD)$")
# An experiment constraint that states a model-call budget ("... under about 600 model calls ...").
_BUDGET = re.compile(r"\d[\d,]*\s+model calls", re.IGNORECASE)


class SubmissionError(RuntimeError):
    """The bundle cannot be built without violating the evidence or secrets rules."""


# ---------------------------------------------------------------------------------------------
# Resource report


@dataclass
class Totals:
    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0

    def add(self, row: dict[str, Any]) -> None:
        self.calls += 1
        self.input_tokens += int(row.get("input_tokens") or 0)
        self.cached_tokens += int(row.get("cached_tokens") or 0)
        self.output_tokens += int(row.get("output_tokens") or 0)
        self.latency_s += float(row.get("latency_s") or 0.0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class StageTime:
    attempts: int = 0
    failed: int = 0
    interrupted: int = 0
    seconds: float = 0.0
    # True when an interrupted attempt contributed only the time up to its last logged event.
    lower_bound: bool = False
    open: bool = False


def module_of(purpose: str) -> str:
    for prefix, label in _MODULES:
        if purpose == prefix or purpose.startswith(prefix + ":"):
            return label
    return purpose.split(":", 1)[0] or "other"


def usage_by(rows: Iterable[dict[str, Any]], key) -> dict[str, Totals]:
    out: dict[str, Totals] = defaultdict(Totals)
    for row in rows:
        out[key(row)].add(row)
    return dict(out)


def _at(event: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(event.get("at")))
    except ValueError:
        return None


def stage_times(events: list[dict[str, Any]]) -> dict[str, StageTime]:
    """Time spent in each stage, from its ``stage.running`` to its ``stage.done``/``stage.failed``.

    A stage that starts again before it finished was interrupted (the process ended); that
    attempt counts only up to the last event it logged, so its total is a lower bound.
    """
    times: dict[str, StageTime] = defaultdict(StageTime)
    started: dict[str, datetime] = {}
    previous: datetime | None = None
    for event in events:
        at = _at(event)
        if at is None:
            continue
        kind, stage = event.get("kind"), str(event.get("stage") or "")
        if kind == "stage.running" and stage:
            if stage in started and previous is not None:
                times[stage].seconds += max(0.0, (previous - started[stage]).total_seconds())
                times[stage].interrupted += 1
                times[stage].lower_bound = True
            started[stage] = at
            times[stage].attempts += 1
        elif kind in ("stage.done", "stage.failed") and stage in started:
            times[stage].seconds += max(0.0, (at - started.pop(stage)).total_seconds())
            times[stage].failed += kind == "stage.failed"
        previous = at
    for stage in started:
        times[stage].open = True
    return dict(times)


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _n(value: int) -> str:
    return f"{value:,}"


def _rate(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "—"


def _latest_row(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    found = [r for r in rows if r.get("name") == name]
    return max(found, key=lambda r: int(r.get("version", 0))) if found else None


def experiment_model_calls(record: Path) -> dict[str, int]:
    """``model_call_count`` that each packaged variant's metrics file reports, when it does."""
    rows = read_jsonl(record / "provenance.jsonl")
    results = _latest_row(rows, "experiment_results")
    if results is None:
        return {}
    calls = {}
    for path in sorted((record / str(results["path"])).glob("*.metrics.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("model_call_count")
        if isinstance(value, int) and not isinstance(value, bool):
            calls[path.name.removesuffix(".metrics.json")] = value
    return calls


def manager_attempts(package: Path) -> dict[str, Path | None]:
    """openJiuwen manager attempts the package's experiment records name, with their directory
    when it still exists on this machine (recovered from the recorded design or code path)."""
    record = package / "run_record"
    attempts: dict[str, Path | None] = {}
    for row in sorted((r for r in read_jsonl(record / "provenance.jsonl") if r.get("name") == "experiments"),
                      key=lambda r: int(r.get("version", 0))):
        data = json.loads((record / str(row["path"])).read_text(encoding="utf-8"))
        match = re.search(r"manager run (\S+?):", str(data.get("notes") or ""))
        if not match:
            continue
        attempt = match.group(1)
        attempts.setdefault(attempt, None)
        for key in ("design_path", "code_dir"):
            parts = Path(str(data.get(key) or "")).parts
            if attempt in parts:
                folder = Path(*parts[: parts.index(attempt) + 1])
                if folder.is_dir():
                    attempts[attempt] = folder
    return attempts


def agent_usage_records(package: Path) -> tuple[list[dict[str, Any]], str]:
    """Usage of openJiuwen's experiment agents and where it was read from.

    Packages record it as ``experiment_usage`` artifacts; for older packages the bundle copies the
    agent traces into ``openjiuwen_agent_traces/`` and the usage is computed from that copy.
    """
    from tyche.experiments.bridge import openjiuwen_usage

    record = package / "run_record"
    rows = sorted((r for r in read_jsonl(record / "provenance.jsonl") if r.get("name") == "experiment_usage"),
                  key=lambda r: int(r.get("version", 0)))
    if rows:
        usages = [json.loads((record / str(r["path"])).read_text(encoding="utf-8")) for r in rows]
        return usages, "run_record/artifacts/experiment_usage/"
    copied = package / AGENT_TRACES
    if copied.is_dir():
        return [openjiuwen_usage(d) for d in sorted(copied.iterdir()) if d.is_dir()], f"{AGENT_TRACES}/"
    return [], ""


def paper_title(package: Path) -> str:
    main = package / "paper_source" / "main.tex"
    if main.exists():
        match = re.search(r"\\title\{(.+?)\}\s*$", main.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return match.group(1).strip()
    return ""


def _usage_table(groups: dict[str, Totals], label: str, order: list[str]) -> list[str]:
    lines = [
        f"| {label} | 调用次数 | 输入 Token | 其中缓存命中 | 输出 Token | 总 Token | 模型耗时 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    total = Totals()
    for name in order:
        t = groups[name]
        lines.append(
            f"| {name} | {t.calls} | {_n(t.input_tokens)} | {_n(t.cached_tokens)} | {_n(t.output_tokens)} "
            f"| {_n(t.total_tokens)} | {_duration(t.latency_s)} |"
        )
        total.calls += t.calls
        total.input_tokens += t.input_tokens
        total.cached_tokens += t.cached_tokens
        total.output_tokens += t.output_tokens
        total.latency_s += t.latency_s
    lines.append(
        f"| **合计** | **{total.calls}** | **{_n(total.input_tokens)}** | **{_n(total.cached_tokens)}** "
        f"| **{_n(total.output_tokens)}** | **{_n(total.total_tokens)}** | **{_duration(total.latency_s)}** |"
    )
    return lines


def resource_report(package: Path, *, team: str = "", commit: str = "") -> str:
    """The resource report for one package, computed only from its run record."""
    record = package / "run_record"
    usage = read_jsonl(record / "usage.jsonl")
    events = read_jsonl(record / "events.jsonl")
    state = json.loads((record / "state.json").read_text(encoding="utf-8"))
    config = json.loads((record / "config.json").read_text(encoding="utf-8")) if (record / "config.json").exists() else {}
    env = json.loads((package / "environment.json").read_text(encoding="utf-8")) if (package / "environment.json").exists() else {}
    stamps = [at for at in (_at(e) for e in events) if at is not None]

    models = sorted({str(r.get("model")) for r in usage if r.get("model")})
    default_model = (config.get("models") or {}).get("default") or {}
    effort = (default_model.get("extra_body") or {}).get("reasoning_effort")
    git = env.get("git") or {}
    built = str(git.get("commit") or "")[:12]

    lines = ["# 资源消耗报告", ""]
    lines.append("由 `scripts/tyche/make_submission.py` 从打包目录的 `run_record/usage.jsonl`（每次模型调用一行）与 "
                 "`run_record/events.jsonl`（阶段事件）计算生成，未经手工修改；原始日志随 `evidence/` 一起提交，可逐行核对。")
    lines.append("")
    meta = [
        ("队伍", team),
        ("论文标题", paper_title(package)),
        ("运行标识", str(state.get("run_id", ""))),
        ("研究方向", str(state.get("direction", ""))),
        ("研究题目", str(state.get("topic", ""))),
        ("模型", ", ".join(models) + (f"（reasoning_effort={effort}）" if effort else "")),
        ("生成论文的代码版本", f"`{built}`" + ("（含未提交改动）" if git.get("dirty") else "") if built else ""),
        ("提交包代码快照", f"`{commit[:12]}`" if commit else ""),
        ("运行起止（UTC）", f"{min(stamps):%Y-%m-%d %H:%M:%S} → {max(stamps):%Y-%m-%d %H:%M:%S}" if stamps else ""),
    ]
    lines += [f"- **{k}**：{v}" for k, v in meta if v]
    lines.append("")

    by_module = usage_by(usage, lambda r: module_of(str(r.get("purpose") or "")))
    module_order = [label for _, label in _MODULES if label in by_module] + sorted(
        set(by_module) - {label for _, label in _MODULES}
    )
    lines += ["## 1. Token 消耗（Tyche 直接发起的模型调用）", ""]
    lines += _usage_table(by_module, "模块", module_order)
    total = Totals()
    for row in usage:
        total.add(row)
    lines += [
        "",
        f"输入 Token 中有 {_n(total.cached_tokens)} 个命中服务端提示缓存（命中率 {_rate(total.cached_tokens, total.input_tokens)}），"
        f"实际未缓存输入 {_n(total.input_tokens - total.cached_tokens)} 个。“模型耗时”是各次调用时延之和，"
        "Tyche 逐个串行发起模型调用，因此它接近这些环节等待模型的时间。",
        "",
    ]

    agent_usages, agent_source = agent_usage_records(package)
    agent_totals = Totals()
    if agent_usages:
        latest = {str(u.get("attempt")): u for u in agent_usages if u.get("attempt")}
        by_agent: dict[str, Totals] = defaultdict(Totals)
        without_usage = failed = 0
        for usage_record in latest.values():
            for module, entry in (usage_record.get("modules") or {}).items():
                t = by_agent[_AGENT_MODULES.get(module, module)]
                t.calls += int(entry.get("calls") or 0)
                t.input_tokens += int(entry.get("input_tokens") or 0)
                t.cached_tokens += int(entry.get("cached_tokens") or 0)
                t.output_tokens += int(entry.get("output_tokens") or 0)
                without_usage += int(entry.get("calls_without_usage") or 0)
                failed += int(entry.get("failed_calls") or 0)
        order = [label for label in _AGENT_MODULES.values() if label in by_agent] + sorted(
            set(by_agent) - set(_AGENT_MODULES.values())
        )
        for name in order:
            t = by_agent[name]
            agent_totals.calls += t.calls
            agent_totals.input_tokens += t.input_tokens
            agent_totals.cached_tokens += t.cached_tokens
            agent_totals.output_tokens += t.output_tokens
        lines += ["### openJiuwen 实验智能体（S2 实验阶段）", ""]
        table = _usage_table(by_agent, "模块", order)
        # openJiuwen's traces time each call too, but the agents overlap with tool execution; no latency column.
        lines += [row.rsplit("|", 2)[0] + "|" for row in table]
        lines += [
            "",
            f"来源：`{agent_source}`，由 openJiuwen 的 ObservabilityRail 为每次模型调用写下的 `agent_trace.jsonl` 汇总"
            f"（{len(latest)} 次 manager 尝试：{', '.join(sorted(latest))}）。"
            + (f"其中 {without_usage} 次调用的记录不含用量，未计入。" if without_usage else "")
            + (f"另有 {failed} 次调用失败。" if failed else ""),
            "",
        ]
        both = total.total_tokens + agent_totals.total_tokens
        lines += [
            "### 合计",
            "",
            "| 来源 | 调用次数 | 输入 Token | 其中缓存命中 | 输出 Token | 总 Token |",
            "|---|---:|---:|---:|---:|---:|",
            f"| Tyche | {total.calls} | {_n(total.input_tokens)} | {_n(total.cached_tokens)} | {_n(total.output_tokens)} "
            f"| {_n(total.total_tokens)} |",
            f"| openJiuwen 实验智能体 | {agent_totals.calls} | {_n(agent_totals.input_tokens)} "
            f"| {_n(agent_totals.cached_tokens)} | {_n(agent_totals.output_tokens)} | {_n(agent_totals.total_tokens)} |",
            f"| **全部** | **{total.calls + agent_totals.calls}** | **{_n(total.input_tokens + agent_totals.input_tokens)}** "
            f"| **{_n(total.cached_tokens + agent_totals.cached_tokens)}** "
            f"| **{_n(total.output_tokens + agent_totals.output_tokens)}** | **{_n(both)}** |",
            "",
        ]

    by_stage = usage_by(usage, lambda r: str(r.get("stage") or ""))
    stage_order = [s for s in _STAGE_NAMES if s in by_stage] + sorted(set(by_stage) - set(_STAGE_NAMES))
    lines += ["### Tyche 调用按阶段", ""]
    lines += _usage_table({_STAGE_NAMES.get(s, s): by_stage[s] for s in stage_order}, "阶段",
                          [_STAGE_NAMES.get(s, s) for s in stage_order])
    lines.append("")

    times = stage_times(events)
    lines += ["## 2. 运行时长", "", "| 阶段 | 运行次数 | 其中失败 | 其中中断 | 累计时长 |", "|---|---:|---:|---:|---:|"]
    active = 0.0
    bound = False
    for stage in [s for s in _STAGE_NAMES if s in times] + sorted(set(times) - set(_STAGE_NAMES)):
        t = times[stage]
        if t.open and not t.seconds:
            shown = "打包时进行中"
        else:
            shown = ("≥ " if t.lower_bound else "") + _duration(t.seconds)
        active += t.seconds
        bound = bound or t.lower_bound
        lines.append(f"| {_STAGE_NAMES.get(stage, stage)} | {t.attempts} | {t.failed} | {t.interrupted} | {shown} |")
    lines += [
        "",
        f"- **各阶段累计运行时长**：{'≥ ' if bound else ''}{_duration(active)}",
        f"- **首末事件跨度**：{_duration((max(stamps) - min(stamps)).total_seconds()) if stamps else '—'}"
        "（包含人工审阅计划、排查问题与续跑之间的间隔）",
        "- 同一阶段的多次运行来自 `--resume` 续跑或 `--from-stage` 重跑；“中断”指进程在该阶段结束前退出，"
        "这类尝试只计到它记录的最后一个事件，因此带 ≥ 的数字是下界。",
        "",
    ]

    lines += ["## 3. 实验阶段（openJiuwen auto_research）", ""]
    exp = times.get("experiments")
    if exp is not None:
        lines.append(f"- 墙钟时长：{'≥ ' if exp.lower_bound else ''}{_duration(exp.seconds)}（{exp.attempts} 次运行）。"
                     "openJiuwen 的实验设计、编码、执行与反思智能体在这段时间内编写并真实执行实验代码。")
    calls = experiment_model_calls(record)
    if calls:
        listed = "，".join(f"{name} {_n(n)}" for name, n in calls.items())
        lines.append(f"- 实验程序自报的被测模型调用次数（各变体指标文件的 `model_call_count`）：{listed}；"
                     f"合计 {_n(sum(calls.values()))}。")
    budget = [c for c in ((config.get("experiments") or {}).get("constraints") or []) if _BUDGET.search(str(c))]
    if budget:
        lines.append(f"- 本次运行交给实验智能体的调用预算约束：“{budget[0]}”")
    if agent_usages:
        lines.append("- openJiuwen 实验智能体（编排、设计、编码、反思）的调用与 token 见第 1 节；"
                     "实验程序对被测模型的调用不经过这些智能体，次数见上一条。")
    else:
        lines.append("- 没有找到 openJiuwen 实验智能体的调用记录（`agent_trace.jsonl`），本报告不含这部分 token，也不做估算。")
    lines.append("")

    lines += ["## 4. 计算资源", ""]
    platform = env.get("platform") or {}
    python = env.get("python") or {}
    oj = env.get("openjiuwen") or {}
    if platform:
        lines.append(f"- 本地执行环境：{platform.get('system', '')} {platform.get('release', '')} "
                     f"({platform.get('machine', '')})，Python {python.get('version', '')}；未使用 GPU。")
    if oj:
        lines.append(f"- openJiuwen agent-core {oj.get('version', '')}，提交 `{str(oj.get('installed_commit', ''))[:12]}`。")
    lines.append("- 模型推理：OpenAI 兼容的托管 API（MaaS），端点地址已在提交包中隐去；各角色的模型设置如下。")
    roles = env.get("models") or {}
    if isinstance(roles, dict) and roles:
        lines += ["", "| 角色 | 模型 | temperature | max_tokens | 额外请求字段 |", "|---|---|---:|---:|---|"]
        for role, spec in roles.items():
            if isinstance(spec, dict):
                extra = json.dumps(spec.get("extra_body") or {}, ensure_ascii=False)
                lines.append(f"| {role} | {spec.get('model_name', '')} | {spec.get('temperature')} "
                             f"| {spec.get('max_tokens')} | `{extra}` |")
    tools = env.get("tools") or {}
    if tools:
        lines.append("")
        lines.append("- 排版工具：" + "；".join(f"{k}: {v}" for k, v in tools.items() if v))
    lines.append("")

    review = config.get("review") or {}
    memory = config.get("memory") or {}
    experiments = config.get("experiments") or {}
    lines += ["## 5. 用量控制措施", ""]
    budgets = memory.get("context_budgets") or {}
    if budgets:
        lines.append("- **上下文预算**：每类调用的上下文在固定 token 预算内装配（"
                     + "，".join(f"{k} {_n(int(v))}" for k, v in budgets.items())
                     + "），可选块按优先级纳入、超出部分截断，装配清单随运行记录保存。")
    lines.append(f"- **提示缓存**：写作与评审调用共享稳定的系统前缀，本次运行输入 Token 的缓存命中率为 "
                 f"{_rate(total.cached_tokens, total.input_tokens)}。")
    if review:
        lines.append(f"- **评审轮数上限**：至多 {review.get('max_rounds')} 轮修订，综合分达到 {review.get('target_composite')} "
                     f"或连续 {review.get('plateau_rounds')} 轮无进步即停止；每轮只重写有待处理发现的章节（至多 "
                     f"{review.get('max_findings_per_revision')} 条）。")
    if experiments:
        lines.append(f"- **实验回合与重试上限**：manager 至多 {experiments.get('max_rounds')} 回合，编码重试 "
                     f"{experiments.get('max_code_retries')} 次，设计修订 {experiments.get('max_design_revisions')} 次，"
                     f"执行重试 {experiments.get('max_execution_retries')} 次，至多 {experiments.get('max_variants')} 个变体。")
    lines.append("- **只重跑需要的阶段**：`--resume` 从第一个未完成阶段继续，`--from-stage` 只重置指定阶段及其后续；"
                 "统计分析与打包不调用模型。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Redaction and secret scanning


def _redact_endpoints(value: Any, found: set[str]) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in ("api_base", "base_url") and isinstance(item, str) and item:
                found.add(item)
                out[key] = REDACTED
            else:
                out[key] = _redact_endpoints(item, found)
        return out
    if isinstance(value, list):
        return [_redact_endpoints(item, found) for item in value]
    return value


def hashed_paths(package: Path) -> set[Path]:
    """Files whose bytes the package's provenance records, which redaction must not touch."""
    record = package / "run_record"
    paths: set[Path] = set()
    for row in read_jsonl(record / "provenance.jsonl"):
        target = record / str(row.get("path", ""))
        if target.is_dir():
            paths.update(p.resolve() for p in target.rglob("*") if p.is_file())
        elif target.exists():
            paths.add(target.resolve())
    paths.add((package / "paper.pdf").resolve())
    return paths


def redacted_copy(package: Path, target: Path) -> set[str]:
    """Copy a package with every model endpoint in its unhashed JSON replaced; returns the endpoints."""
    shutil.copytree(package, target)
    protected = hashed_paths(target)
    endpoints: set[str] = set()
    for name in ("environment.json", "run_record/config.json"):
        path = target / name
        if path.exists() and path.resolve() not in protected:
            data = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(_redact_endpoints(data, endpoints), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return endpoints


def secret_values(env: dict[str, str] | None = None, dotenv_files: Iterable[Path] = ()) -> set[str]:
    """Credential values present in the environment or the git-ignored .env files."""
    values: set[str] = set()
    sources: list[dict[str, Any]] = [dict(os.environ if env is None else env)]
    for path in dotenv_files:
        if path.exists():
            from dotenv import dotenv_values

            sources.append(dict(dotenv_values(path, interpolate=False)))
    for source in sources:
        for key, value in source.items():
            if value and _SECRET_ENV.search(str(key)) and len(str(value)) >= 12:
                values.add(str(value))
    return values


def scan_bundle(root: Path, secrets: set[str], hosts: set[str]) -> tuple[list[str], list[str]]:
    """(files holding a credential, files naming a redacted endpoint host).

    Credential values are searched in every file; key-shaped strings and endpoint hosts only outside
    ``code/`` and ``docs/``, which hold the public repository's own text (its tests carry fictional
    key-shaped fixtures and its defaults name public endpoints). A host inside a hashed artifact,
    e.g. an experiment program that recorded its settings, cannot be removed without breaking
    verification, so hosts are reported rather than refused.
    """
    secret_needles = [s.encode("utf-8") for s in secrets]
    host_needles = [h.encode("utf-8") for h in hosts if h]
    leaks, mentions = [], []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        data = path.read_bytes()
        outside = rel.parts[0] not in ("code", "docs")
        text = data.decode("utf-8", errors="ignore") if outside else ""
        if any(n in data for n in secret_needles) or any(p.search(text) for p in _SECRET_PATTERNS):
            leaks.append(rel.as_posix())
        elif outside and any(n in data for n in host_needles):
            mentions.append(rel.as_posix())
    return leaks, mentions


def _host(url: str) -> str:
    match = re.match(r"^[a-z]+://([^/:]+)", url.strip(), re.IGNORECASE)
    return match.group(1) if match else url.strip()


# ---------------------------------------------------------------------------------------------
# Code snapshot


def git_commit(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()


def uncommitted(repo: Path, paths: Iterable[str]) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", *paths], check=True,
                         capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def snapshot_code(repo: Path, target: Path, commit: str) -> None:
    """Extract Tyche's files at ``commit`` (tracked files only) into ``target``."""
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit, "--", *CODE_PATHS],
                             check=True, capture_output=True).stdout
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="data")


def requirements(repo: Path) -> str:
    """The locked dependency set of the environment the paper was produced in."""
    out = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "--extra", "test"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    header = ("# Exact dependency pins exported from the repository's uv.lock (uv export --frozen --no-hashes\n"
              "# --no-emit-project --extra test). Install with --no-deps; see run_guide.md.\n")
    return header + out


def run_config_yaml(package: Path, run_id: str) -> str:
    """The run's saved configuration as a --config file, with the endpoint read from the environment."""
    data = json.loads((package / "run_record" / "config.json").read_text(encoding="utf-8"))
    models = data.get("models") or {}
    for spec in models.values():
        if isinstance(spec, dict) and spec.get("api_base"):
            spec["api_base"] = "${API_BASE}"
    default = models.get("default") or {}
    # The same environment variables as the packaged defaults, with this run's values as fallbacks.
    for key, var in (("provider", "MODEL_PROVIDER"), ("model_name", "MODEL_NAME"), ("context_window", "MODEL_CONTEXT_WINDOW")):
        if default.get(key) not in (None, ""):
            default[key] = f"${{{var}:-{default[key]}}}"
    header = (
        f"# Effective configuration of run {run_id} (run_record/config.json in evidence/{run_id}/).\n"
        "# The endpoint comes from ${API_BASE}; MODEL_PROVIDER, MODEL_NAME and MODEL_CONTEXT_WINDOW override\n"
        "# the run's own values. Credentials never appear here: the key is read from the environment\n"
        "# variable named by api_key_env. Use it as\n"
        "#   python main.py run --config config.yaml --topic ... --direction ...\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110)


# ---------------------------------------------------------------------------------------------
# Bundle


@dataclass
class BundleResult:
    root: Path
    run_id: str
    commit: str
    todo: list[str] = field(default_factory=list)
    redacted_hosts: list[str] = field(default_factory=list)
    host_mentions: list[str] = field(default_factory=list)
    agent_traces_missing: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readme(team: str, run_id: str, commit: str, title: str, repo_url: str) -> str:
    return f"""# {team} · CCF BDCI 2026 openJiuwen 赛道提交包

论文：**{title}**（`paper/paper.pdf`，ICLR 2027 模板，英文）

| 路径 | 内容 |
|---|---|
| `Agentic Reviewer/PaperReview-AccessToken.txt` | paperreview.ai 评审 access token（ICLR 模板） |
| `paper/paper.pdf` | 提交论文 |
| `code/` | `main.py` 入口、`config.yaml` 本论文的运行配置、`requirements.txt` 锁定依赖、`run_guide.md` 复现指南，以及 Tyche 全部源码与测试 |
| `docs/` | `architecture.md` 架构设计、`module_call.md` openJiuwen 模块调用说明、`innovation.md` 创新点 |
| `evidence/{run_id}/` | 生成这篇论文的完整打包目录：LaTeX 源码、全部产物版本、实验指标与生成代码、评审台账、论断–证据地图、溯源清单（运行配置中的模型端点已隐去）；openJiuwen 实验智能体的调用记录在 `run_record/artifacts/experiment_traces/` 或 `{AGENT_TRACES}/` |
| `resource_report.md` | Token 消耗与运行时长，由运行日志计算 |
| `framework_contribution.md` | 框架贡献与 PR 链接 |
| `SHA256SUMS` | 本目录全部文件的 SHA-256 |

代码仓库：{repo_url}（本包代码快照对应提交 `{commit}`）。

离线核验论文中的每个数字与引用（不需要网络与模型密钥）：

```bash
cd code
python main.py verify ../evidence/{run_id}
```
"""


def run_section(package: Path, run_id: str, notes_file: str = "") -> str:
    """The run guide's section with this paper's own topic, direction, and commands.

    ``notes_file`` (relative to ``code/``) holds the planner notes of a run made before notes were
    recorded in the run record.
    """
    record = package / "run_record"
    state = json.loads((record / "state.json").read_text(encoding="utf-8"))
    topic = str(state.get("topic") or "").replace("\\", "\\\\").replace('"', '\\"')
    direction = str(state.get("direction") or "")
    seed = (state.get("meta") or {}).get("analysis_seed")
    notes = _latest_row(read_jsonl(record / "provenance.jsonl"), "operator_notes")
    notes_path = f"../evidence/{run_id}/run_record/{notes['path']}" if notes else notes_file
    notes_arg = f" \\\n  --notes {notes_path}" if notes_path else ""
    rows = [("运行编号", f"`{run_id}`"), ("研究方向", f"`{direction}`"), ("题目", str(state.get("topic") or ""))]
    if seed is not None:
        rows.append(("分析随机种子", f"`{seed}`"))
    if notes:
        rows.append(("规划时的人工备注", f"`{notes_path}`"))
    elif notes_path:
        rows.append(("规划时的人工备注", f"`{notes_path}`（该运行早于备注入档功能，备注取自仓库 `docs/tyche/runs/`）"))
    table = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"""
## 本提交论文的运行参数

| 项 | 值 |
|---|---|
{table}

```bash
python main.py run --config config.yaml --run-id {run_id}-repro \\
  --topic "{topic}" \\
  --direction {direction}{notes_arg} --stop-after plan
python main.py run --resume --run-id {run_id}-repro
```
"""


def build_bundle(
    *,
    repo: Path,
    package: Path,
    out_dir: Path,
    team: str,
    token_file: Path | None = None,
    repo_url: str = "https://github.com/sweetcornna/Tyche",
    replace: bool = False,
) -> BundleResult:
    from tyche.trace.verify import locate_package, report, verify_package

    repo = repo.resolve()
    package = locate_package(package)
    if not team.strip() or any(c in team for c in "/\\") or team.strip() in {".", ".."}:
        raise SubmissionError(f"team name {team!r} cannot be used as a directory name")
    if not (package / "paper.pdf").exists():
        raise SubmissionError("the package has no verified paper.pdf (an UNVERIFIED package cannot be submitted)")
    checks = verify_package(package)
    if not report(checks)["passed"]:
        failed = "; ".join(f"{c.name}: {c.detail}" for c in checks if not c.ok)
        raise SubmissionError(f"tyche verify fails on {package}: {failed}")
    dirty = uncommitted(repo, [*CODE_PATHS, str(SUBMISSION_DOCS), str(TEMPLATES), "uv.lock"])
    if dirty:
        raise SubmissionError("commit these files first; the code snapshot is taken from HEAD: " + ", ".join(dirty[:8]))

    root = out_dir.resolve() / team.strip()
    if root.exists():
        if not replace:
            raise SubmissionError(f"{root} already exists (pass --replace to rebuild it)")
        shutil.rmtree(root)
    state = json.loads((package / "run_record" / "state.json").read_text(encoding="utf-8"))
    run_id = str(state.get("run_id") or package.parent.name)
    commit = git_commit(repo)
    result = BundleResult(root=root, run_id=run_id, commit=commit)
    try:
        # Agentic Reviewer token: supplied by the team after uploading the paper themselves.
        token_dir = root / "Agentic Reviewer"
        token_dir.mkdir(parents=True)
        token = token_file.read_text(encoding="utf-8").strip() if token_file else ""
        if token_file and (not token or len(token.splitlines()) != 1):
            raise SubmissionError(f"{token_file} must contain exactly one non-empty line (the access token)")
        (token_dir / "PaperReview-AccessToken.txt").write_text((token or TOKEN_PLACEHOLDER) + "\n", encoding="utf-8")
        if not token:
            result.todo.append("把 paperreview.ai 的 access token 写入 Agentic Reviewer/PaperReview-AccessToken.txt"
                               "（或重新运行并传入 --review-token-file）")

        (root / "paper").mkdir()
        shutil.copy2(package / "paper.pdf", root / "paper" / "paper.pdf")

        code = root / "code"
        snapshot_code(repo, code, commit)
        shutil.copy2(repo / TEMPLATES / "main.py", code / "main.py")
        shutil.copy2(repo / TEMPLATES / "setup_env.sh", code / "setup_env.sh")
        shutil.copy2(repo / TEMPLATES / "pytest.ini", code / "pytest.ini")
        (code / "setup_env.sh").chmod(0o755)
        notes_file = ""
        repo_notes = repo / "docs" / "tyche" / "runs" / f"{run_id}.notes.md"
        if repo_notes.exists():
            (code / "run_notes").mkdir()
            shutil.copy2(repo_notes, code / "run_notes" / repo_notes.name)
            notes_file = f"run_notes/{repo_notes.name}"
        guide = (repo / SUBMISSION_DOCS / "run_guide.md").read_text(encoding="utf-8")
        section = run_section(package, run_id, notes_file)
        (code / "run_guide.md").write_text(guide.rstrip("\n") + "\n" + section, encoding="utf-8")
        (code / "requirements.txt").write_text(requirements(repo), encoding="utf-8")
        (code / "config.yaml").write_text(run_config_yaml(package, run_id), encoding="utf-8")

        (root / "docs").mkdir()
        for name in ("architecture.md", "module_call.md", "innovation.md"):
            shutil.copy2(repo / SUBMISSION_DOCS / name, root / "docs" / name)
        shutil.copy2(repo / "docs" / "tyche" / "DESIGN.md", root / "docs" / "design_details.md")
        shutil.copy2(repo / SUBMISSION_DOCS / "framework_contribution.md", root / "framework_contribution.md")

        evidence = root / "evidence" / run_id
        endpoints = redacted_copy(package, evidence)
        result.redacted_hosts = sorted({_host(e) for e in endpoints})
        if not agent_usage_records(evidence)[0]:
            from tyche.experiments.bridge import collect_agent_traces

            for attempt, folder in manager_attempts(evidence).items():
                if folder is None or not collect_agent_traces(folder, evidence / AGENT_TRACES):
                    result.agent_traces_missing.append(attempt)
        rechecked = verify_package(evidence)
        if not report(rechecked)["passed"]:
            failed = "; ".join(f"{c.name}: {c.detail}" for c in rechecked if not c.ok)
            raise SubmissionError(f"the redacted evidence copy no longer verifies: {failed}")

        (root / "resource_report.md").write_text(resource_report(evidence, team=team.strip(), commit=commit),
                                                 encoding="utf-8")
        (root / "README.md").write_text(_readme(team.strip(), run_id, commit, paper_title(package), repo_url),
                                        encoding="utf-8")

        secrets = secret_values(dotenv_files=[repo / ".env", Path.home() / ".jiuwenswarm" / "config" / ".env"])
        leaks, result.host_mentions = scan_bundle(root, secrets, set(result.redacted_hosts))
        if leaks:
            raise SubmissionError("credential text found in: " + ", ".join(leaks[:10]))
        if result.host_mentions:
            result.todo.append(f"{len(result.host_mentions)} 个文件仍含模型端点主机名（多为带哈希的实验产物，改动会使核验失败）："
                               "确认可以公开，或改用不记录端点的实验重跑")
        if result.agent_traces_missing:
            result.todo.append("没有找到这些 openJiuwen 尝试的 agent_trace.jsonl，资源报告缺少其 token："
                               + ", ".join(result.agent_traces_missing))

        sums = [f"{_sha256(p)}  {p.relative_to(root).as_posix()}" for p in sorted(root.rglob("*")) if p.is_file()]
        (root / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return result
