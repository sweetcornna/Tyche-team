"""The paper's author as one agent session: drafting, revising, repairing, and shortening.

:class:`AgentAuthor` has the interface the composer and the revision loop use for
:class:`tyche.paper.writer.SectionWriter`, so the deterministic harness around it (builds,
gates, the review panel, acceptance tests, rollback) is unchanged. What changes is how the
text is produced: instead of one model call per section, one long-lived agent session
works through tools (see :mod:`tyche.agent.desk`), checks its own edits, and cannot end a
task while the host's checks still fail, up to a bounded number of hand-backs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from tyche.agent.desk import Materials, PaperDesk
from tyche.agent.inbox import OperatorInbox
from tyche.agent.policy import PermissionPolicy
from tyche.agent.session import AgentSession, Hooks, Subagent, delegate_tool
from tyche.agent.todos import Todo, TodoList
from tyche.agent.tools import Tool, ToolResult
from tyche.memory import Block, MemoryStore, memory_block, wrap_block
from tyche.paper.sanitize import SanitizeReport
from tyche.paper.writer import WRITE_ORDER, SECTION_GUIDANCE, SectionDraft, WritingContext
from tyche.prompts import load_prompt
from tyche.textutil import count_tokens, word_count
from tyche.workspace import StageError, write_json_atomic

if TYPE_CHECKING:
    from tyche.llm import LLMClient
    from tyche.paper.compose import PaperComposer


@dataclass
class AgentSettings:
    """The ``agents`` block of the configuration."""

    enabled: bool = True
    permission_mode: str = "workspace_write"
    deny_tools: list[str] = field(default_factory=list)
    max_turns: dict[str, int] = field(default_factory=dict)
    max_stop_blocks: int = 3
    # Compact a session when its history reaches this share of the model's context window.
    compact_at: float = 0.6
    subagents: bool = True
    reviewer_tools: bool = True
    planner_tools: bool = True
    planner_searches: int = 4

    DEFAULT_TURNS = {"draft": 60, "revise": 30, "repair": 8, "shorten": 10, "review": 6, "helper": 8, "plan": 12}

    @classmethod
    def from_config(cls, data: dict[str, Any] | None) -> "AgentSettings":
        data = dict(data or {})
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        settings = cls(**known)
        settings.max_turns = {**cls.DEFAULT_TURNS, **{k: int(v) for k, v in (settings.max_turns or {}).items()}}
        settings.deny_tools = list(settings.deny_tools or [])
        return settings

    def turns(self, task: str) -> int:
        return int(self.max_turns.get(task, self.DEFAULT_TURNS.get(task, 20)))

    def policy(self, mode: str | None = None) -> PermissionPolicy:
        return PermissionPolicy(mode or self.permission_mode, deny=set(self.deny_tools))


def major_kind(finding) -> tuple[str, str, str]:
    """A gate finding with its counts masked, so "812 words" and "700 words" are the same problem."""
    return (finding.gate, finding.section, re.sub(r"\d+(?:\.\d+)?", "#", finding.message))


class RespondArgs(BaseModel):
    id: str = Field(description="The finding's id.")
    action: Literal["fixed", "rebutted"]
    note: str = Field(description="One sentence: what changed, or why the finding is wrong.")


def section_contracts(contracts: dict[str, dict[str, Any]], ctx: WritingContext) -> dict[str, Any]:
    """Every section's goal, requirements, and word range, as the author agent sees them."""
    out: dict[str, Any] = {}
    fill = {"{method_name}": ctx.plan.method_name}
    for name in WRITE_ORDER:
        guide = SECTION_GUIDANCE[name]
        limits = contracts.get(name) or {}
        fill["{min_citations}"] = str(limits.get("min_citations", 6))
        reqs = []
        for req in guide["requirements"]:
            for placeholder, value in fill.items():
                req = req.replace(placeholder, value)
            reqs.append(req)
        out[name] = {
            "goal": guide["goal"],
            "requirements": reqs,
            "min_words": limits.get("min_words"),
            "max_words": limits.get("max_words"),
            "may_cite": name not in ("abstract", "conclusion"),
        }
    return out


class AgentAuthor:
    def __init__(
        self,
        llm: "LLMClient",
        *,
        memory: MemoryStore,
        contracts: dict[str, dict[str, Any]],
        settings: AgentSettings,
        work_dir: Path,
        context_tokens: int,
        evidence_limit: int = 12,
        lessons_limit: int = 8,
        materials: Materials | None = None,
        helper_llm: "LLMClient | None" = None,
        manifest_dir: Path | None = None,
        log=None,
        inbox: OperatorInbox | None = None,
    ):
        self.llm = llm
        self.inbox = inbox
        self.helper_llm = helper_llm or llm
        self.memory = memory
        self.contracts = contracts
        self.settings = settings
        self.work_dir = work_dir
        self.context_tokens = context_tokens
        self.evidence_limit = evidence_limit
        self.lessons_limit = lessons_limit
        self.materials = materials or Materials()
        self.manifest_dir = manifest_dir
        self.log = log or (lambda *a, **k: None)
        self.composer: "PaperComposer | None" = None
        self.desk: PaperDesk | None = None
        self.session: AgentSession | None = None
        self.todos = TodoList(on_change=lambda todos: self.log("agent.todos", session="author", todos=todos.to_list()))
        self._responses: dict[str, dict[str, str]] = {}
        self._expected: list[str] = []
        self._known_majors: set[tuple[str, str, str]] = set()
        # Citation keys the session has been told about; keys admitted later are announced in the next task.
        self._announced: set[str] = set()
        self._helpers = 0
        # Item ids of the lessons in the author's context, for the evolve stage's bookkeeping.
        self.lesson_ids: list[str] = []

    # -- setup ------------------------------------------------------------------
    def bind(self, composer: "PaperComposer") -> None:
        self.composer = composer
        self.desk = PaperDesk(
            composer, self.memory, composer.ctx.run_id, self.work_dir / "builds", self.materials, log=self.log
        )
        self.session = self._build_session()
        self._announced = {c["key"] for c in composer.ctx.citations}

    def _context(self, ctx: WritingContext) -> str:
        blocks = [
            Block("research_plan", ctx.plan.model_dump_json(indent=1)),
            Block("allowed_citations", json.dumps(ctx.citations, ensure_ascii=False, indent=1)),
            Block("available_labels", json.dumps(ctx.labels, indent=1)),
            Block("results_brief", ctx.results_brief),
            Block("section_contracts", json.dumps(section_contracts(self.contracts, ctx), ensure_ascii=False, indent=1)),
        ]
        if ctx.design_excerpt:
            blocks.append(Block("experiment_design", ctx.design_excerpt))
        if ctx.reflection_excerpt:
            blocks.append(Block("experiment_reflection", ctx.reflection_excerpt))
        survey = {k: ctx.synthesis.get(k) for k in ("gap", "themes", "open_problems")}
        blocks.append(Block("survey_synthesis", json.dumps(survey, ensure_ascii=False, indent=1)))
        query = " ".join([ctx.plan.working_title, ctx.plan.problem, ctx.plan.method_sketch, *ctx.plan.keywords])
        blocks.append(
            memory_block(self.memory, "evidence", query, kinds=["evidence"], run_id=ctx.run_id, limit=self.evidence_limit)
        )
        lessons = memory_block(
            self.memory,
            "lessons",
            f"{ctx.plan.working_title} {' '.join(WRITE_ORDER)}",
            kinds=["lesson"],
            run_id=ctx.run_id,
            limit=self.lessons_limit,
            scopes=["global", "project"],
            extra_filter=lambda item: item.meta.get("status") == "active",
        )
        blocks.append(lessons)
        self.lesson_ids = list(lessons.item_ids)
        self.memory.touch([i for b in blocks for i in b.item_ids])
        if self.manifest_dir is not None:
            # The same manifest shape the section writer saves, so audits and the evolve stage read both.
            write_json_atomic(
                self.manifest_dir / "000_agent_author.json",
                {
                    "agent": "author",
                    "budget": self.context_tokens,
                    "used": sum(count_tokens(wrap_block(b)) for b in blocks),
                    "included": [
                        {"name": b.name, "tokens": count_tokens(wrap_block(b)), "item_ids": list(b.item_ids)}
                        for b in blocks
                    ],
                    "dropped": [],
                },
            )
        return "\n\n".join(wrap_block(b) for b in blocks)

    def _fact_checker(self) -> Subagent:
        assert self.desk is not None and self.composer is not None
        desk, ctx = self.desk, self.composer.ctx

        def build() -> AgentSession:
            self._helpers += 1
            return AgentSession(
                self.helper_llm,
                name="fact_checker",
                instructions=load_prompt("agent_fact_checker"),
                tools=desk.read_tools(),
                policy=self.settings.policy("read_only"),
                context=self._context(ctx),
                max_turns=self.settings.turns("helper"),
                compact_at_tokens=int(self.context_tokens * self.settings.compact_at),
                transcript=self.work_dir / "transcripts" / f"fact_checker_{self._helpers:02d}.jsonl",
                log=self.log,
            )

        return Subagent(
            "fact_checker",
            "checks named sections or claims against the results, the design, and the cited evidence, and "
            "lists every unfaithful statement with a fix",
            build,
        )

    def _build_session(self) -> AgentSession:
        assert self.desk is not None and self.composer is not None
        tools: list[Tool] = self.desk.read_tools() + self.desk.edit_tools()
        tools.append(Tool("respond_to_finding", "Record your response to a review finding: fixed (say what "
                          "changed) or rebutted (say why the finding is wrong).", self._respond, RespondArgs,
                          effect="edit"))
        if self.settings.subagents:
            tools.append(delegate_tool([self._fact_checker()], log=self.log))
        return AgentSession(
            self.llm,
            name="author",
            instructions=load_prompt("agent_author"),
            tools=tools,
            policy=self.settings.policy(),
            context=self._context(self.composer.ctx),
            hooks=Hooks(on_stop=[self._stop_check], before_turn=[self._autosave]),
            todos=self.todos,
            max_stop_blocks=self.settings.max_stop_blocks,
            compact_at_tokens=int(self.context_tokens * self.settings.compact_at),
            state_fn=self.desk.status,
            transcript=self.work_dir / "transcripts" / "author.jsonl",
            log=self.log,
            inbox=self.inbox,
        )

    def _require(self) -> tuple["PaperComposer", PaperDesk, AgentSession]:
        if self.composer is None or self.desk is None or self.session is None:
            raise RuntimeError("AgentAuthor is not bound to a composer")
        return self.composer, self.desk, self.session

    # -- tools and checks ----------------------------------------------------------
    def _respond(self, args: RespondArgs) -> ToolResult:
        if self._expected and args.id not in self._expected:
            return ToolResult(f"no open finding {args.id!r} in this task; expected one of {', '.join(self._expected)}", ok=False)
        self._responses[args.id] = {"id": args.id, "action": args.action, "note": args.note}
        return ToolResult(f"recorded {args.action} for {args.id}")

    async def _stop_check(self, _session: AgentSession) -> str | None:
        composer, desk, _ = self._require()
        problems: list[str] = []
        missing = desk.missing()
        if missing:
            problems.append("sections not written yet: " + ", ".join(missing))
        if self._mode == "draft" and not desk.title_set:
            problems.append("the paper has no title yet; call set_title")
        unanswered = [i for i in self._expected if i not in self._responses]
        if unanswered:
            problems.append("findings without a response (respond_to_finding): " + ", ".join(unanswered))
        if self._mode in ("draft", "revise") and not missing:
            if desk.dirty or desk.last_build is None:
                await desk.build()
            build = desk.last_build
            assert build is not None
            # A draft must clear every major finding it can; a revision must not add new ones (the
            # revision loop would reject it), but need not fix majors the findings did not raise.
            serious = [
                f for f in build.gates.findings
                if f.severity == "blocker"
                or (f.severity == "major" and (self._mode == "draft" or major_kind(f) not in self._known_majors))
            ]
            if not build.compile.ok:
                errors = "; ".join(f"{e.file}:{e.line}: {e.message}" for e in build.compile.errors[:3])
                problems.append(f"the paper does not compile: {errors}")
            if serious:
                problems.append("build_paper reports:\n" + desk.render_findings(serious, limit=15))
        return "\n".join(problems) or None

    # -- tasks -----------------------------------------------------------------------
    _mode = "draft"

    async def _run(self, mode: str, task: str, *, expected: list[str] | None = None) -> Any:
        _, desk, session = self._require()
        self._mode = mode
        self._expected = list(expected or [])
        self._responses = {}
        # The harness may have restored or rebuilt the draft since this desk's last build.
        desk.dirty = True
        self._known_majors = {major_kind(f) for f in desk.lint() if f.severity == "major"}
        outcome = await session.run(task, max_turns=self.settings.turns(mode))
        self.log("agent.outcome", session="author", mode=mode, status=outcome.status, turns=outcome.turns,
                 calls=outcome.tool_calls)
        return outcome

    @property
    def autosave_path(self) -> Path:
        return self.work_dir / "author_session.json"

    def _autosave(self, session: AgentSession, message: str) -> None:
        """Save the drafting session before each turn, so an interrupted write stage resumes where it stopped."""
        if self._mode != "draft" or self.composer is None or self.desk is None:
            return
        write_json_atomic(
            self.autosave_path,
            {
                "mode": "draft",
                "next_message": message,
                "session": session.export_state(),
                "sections": dict(self.composer.sections),
                "removed": {k: list(v) for k, v in self.composer.removed.items()},
                "title": self.composer.title,
                "title_set": self.desk.title_set,
            },
        )

    def _resume_draft(self) -> bool:
        """Restore an interrupted draft saved by :meth:`_autosave`, if it belongs to this session."""
        composer, desk, session = self._require()
        if not self.autosave_path.exists():
            return False
        try:
            saved = json.loads(self.autosave_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if saved.get("mode") != "draft" or not session.import_state(saved.get("session")):
            self.log("agent.resume_skipped", session="author", reason="context changed since the save")
            return False
        composer.sections.update(saved.get("sections") or {})
        composer.removed.update(saved.get("removed") or {})
        composer.title = saved.get("title") or composer.title
        desk.title_set = bool(saved.get("title_set"))
        session.resume_with(str(saved.get("next_message") or ""))
        self.log("agent.resumed", session="author", sections=sorted(n for n, b in composer.sections.items() if b.strip()))
        return True

    async def draft_paper(self, composer: "PaperComposer") -> None:
        if self.composer is not composer:
            self.bind(composer)
        _, desk, _ = self._require()
        resumed = self._resume_draft()
        if not resumed:
            self.todos.set(
                [Todo(name, f"Write the {name.replace('_', ' ')} section.") for name in WRITE_ORDER]
                + [Todo("title", "Set the title."), Todo("verify", "Run build_paper and fix what it reports.")]
            )
        task = (
            "Write the complete paper: all seven sections (" + ", ".join(WRITE_ORDER) + ") and its title. "
            "Your todo list holds a suggested order: substance first, framing last. Write one section per reply "
            "and fix what its checks report before the next. After the last section, run build_paper and fix "
            "every blocker and every major finding you can. Finish with a reply without a tool call once the "
            "checks pass."
        )
        if resumed:
            task = ("Your session was interrupted and has been resumed; the draft and your todo list are as you left "
                    "them (paper_status shows the draft). Continue the task:\n" + task)
        outcome = await self._run("draft", task)
        missing = desk.missing()
        if missing:
            self.log("agent.missing_sections", sections=missing, status=outcome.status)
            await self._run("draft", "These sections are still not written: " + ", ".join(missing)
                            + ". Write them now, then run build_paper and fix what it reports.")
            missing = desk.missing()
        if missing:
            raise StageError(
                f"the author agent stopped ({outcome.status}) without writing: {', '.join(missing)}; "
                "rerun the write stage (it resumes this session) or raise agents.max_turns.draft"
            )
        self.autosave_path.unlink(missing_ok=True)

    async def revise_paper(self, findings: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Address review findings in one task; returns the author's responses (fixed or rebutted)."""
        composer, _, _ = self._require()
        admitted = [c for c in composer.ctx.citations if c["key"] not in self._announced]
        self._announced.update(c["key"] for c in admitted)
        self.todos.set([Todo(f["id"], f"{f['severity']} in {f.get('section', 'general')}: {f['problem'][:140]}")
                        for f in findings])
        parts = [
            "The review panel reported the findings below (JSON). Address each one: change the paper where it "
            "needs to change, then record your response with respond_to_finding (fixed, or rebutted when the "
            "finding is wrong). Change only what the findings require; keep correct content, citations, and "
            "numbers intact, and do not over-correct. A finding that asks for new experiments is answered by "
            "narrowing the claim. Finally run build_paper and fix what it reports.",
            "<findings_to_address>\n" + json.dumps(findings, ensure_ascii=False, indent=1) + "\n</findings_to_address>",
        ]
        if admitted:
            parts.append(
                "These papers were verified and added to the bibliography since you started; you may now cite them:\n"
                + json.dumps(admitted, ensure_ascii=False, indent=1)
            )
        await self._run("revise", "\n\n".join(parts), expected=[f["id"] for f in findings])
        return list(self._responses.values())

    def _draft_of(self, name: str) -> SectionDraft:
        composer, _, _ = self._require()
        body = composer.sections.get(name, "")
        report = SanitizeReport(removed_citations=list(composer.removed.get(name, [])))
        return SectionDraft(name=name, latex=body, report=report, words=word_count(body))

    async def repair(self, name: str, ctx: WritingContext, current: str, error: str) -> SectionDraft:
        await self._run(
            "repair",
            f"The paper fails to compile. The first error points at the {name.replace('_', ' ')} section:\n"
            f"<latex_error>\n{error}\n</latex_error>\nFix only the LaTeX problem; do not change wording or content "
            "otherwise. Reply without a tool call when it is fixed.",
        )
        return self._draft_of(name)

    async def shorten(self, name: str, ctx: WritingContext, current: str, target_words: int) -> SectionDraft:
        await self._run(
            "shorten",
            f"The paper exceeds its page limit. Shorten the {name.replace('_', ' ')} section to at most "
            f"{target_words} words (it has {word_count(current)}). Remove repetition and secondary detail first; "
            "keep every citation that supports a claim, every reported number that remains, and all \\ref labels. "
            "Keep the section's contract requirements. Reply without a tool call when done.",
        )
        return self._draft_of(name)

    # -- state ------------------------------------------------------------------------
    def checkpoint(self):
        _, _, session = self._require()
        return session.checkpoint(), set(self._announced)

    def rollback(self, state) -> None:
        _, _, session = self._require()
        session_state, announced = state
        session.rollback(session_state)
        self._announced = announced

    def export_state(self) -> dict[str, Any] | None:
        if self.session is None:
            return None
        return {"agent": "author", **self.session.export_state()}

    def import_state(self, state: dict[str, Any] | None, ctx: WritingContext) -> bool:
        if self.session is None or not state or state.get("agent") != "author":
            return False
        return self.session.import_state(state)
