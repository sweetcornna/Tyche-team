"""The paper as a workspace that agents read, edit, and check through tools.

Every tool here is deterministic host code over the paper composer. Edits are sanitized
and checked as soon as they land, the way a coding agent's edits are followed by a
linter; ``build_paper`` compiles the paper and runs every gate, the way its changes are
followed by the test suite. Nothing here lets a model add a number to the registry, a key
to the bibliography, or a pass to a gate.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from tyche.agent.tools import Tool, ToolResult
from tyche.gates import GateFinding
from tyche.gates.checks import (
    check_citations,
    check_internal_terms,
    check_numbers,
    check_placeholders,
    check_structure,
)
from tyche.paper.sanitize import sanitize_section
from tyche.paper.writer import WRITE_ORDER
from tyche.textutil import truncate_tokens, word_count

if TYPE_CHECKING:
    from tyche.memory import MemoryStore
    from tyche.paper.compose import BuildResult, PaperComposer

_FENCE = re.compile(r"```(?:latex|tex)?\s*\n(.*?)\n?```", re.S)
SectionName = Literal["abstract", "introduction", "related_work", "method", "experiments", "analysis", "conclusion"]
NO_CITATIONS = ("abstract", "conclusion")


class SectionArg(BaseModel):
    section: SectionName


class WriteArgs(BaseModel):
    section: SectionName
    latex: str = Field(description="The complete section body in LaTeX, without the \\section command.")


class EditArgs(BaseModel):
    section: SectionName
    old: str = Field(description="Exact text currently in the section, long enough to occur only once.")
    new: str = Field(description="The replacement text.")
    replace_all: bool = Field(default=False, description="Replace every occurrence instead of exactly one.")


class LintArgs(BaseModel):
    section: SectionName | None = Field(default=None, description="One section, or omit for the whole paper.")


class QueryArgs(BaseModel):
    query: str = Field(description="Words to look for.")


class TitleArgs(BaseModel):
    title: str = Field(description="At most 14 words, no LaTeX, no quotes.")


class MaterialArgs(BaseModel):
    name: Literal["experiment_design", "experiment_reflection"]


@dataclass
class Materials:
    """Longer run materials an agent may page in; the context holds only excerpts of them."""

    experiment_design: str = ""
    experiment_reflection: str = ""


@dataclass
class PaperDesk:
    composer: "PaperComposer"
    memory: "MemoryStore"
    run_id: str
    build_root: Path
    materials: Materials = field(default_factory=Materials)
    log: Any = None
    # Whether the draft changed since the last build, and that build's result.
    dirty: bool = True
    last_build: "BuildResult | None" = None
    builds: int = 0
    edits: int = 0
    title_set: bool = False

    # -- state ----------------------------------------------------------------
    @property
    def sections(self) -> dict[str, str]:
        return self.composer.sections

    def allowed_keys(self, name: str) -> set[str]:
        if name in NO_CITATIONS:
            return set()
        return {c["key"] for c in self.composer.ctx.citations}

    def missing(self) -> list[str]:
        return [n for n in WRITE_ORDER if not self.sections.get(n, "").strip()]

    def lint(self, name: str | None = None) -> list[GateFinding]:
        """Every gate that needs no compilation, over the current draft (or one section of it)."""
        c = self.composer
        sections = {n: b for n, b in self.sections.items() if b.strip()}
        findings = check_numbers(sections, c.registry)
        cites, _ = check_citations(
            sections, c.bib_keys, int((c.contracts.get("related_work") or {}).get("min_citations", 6)), c.removed
        )
        findings += cites
        structure = check_structure(sections, c.contracts, c.labels)
        # Missing sections are reported by status(); here they would only repeat it.
        findings += [f for f in structure if f.message not in ("section is missing or empty", "abstract is missing")]
        findings += check_placeholders(sections)
        findings += check_internal_terms(sections)
        if name is not None:
            findings = [f for f in findings if f.section == name]
        return findings

    def status(self) -> str:
        c = self.composer
        rows = [f"title: {c.title}"]
        for name in WRITE_ORDER:
            body = self.sections.get(name, "")
            limits = c.contracts.get(name) or {}
            span = f"{limits.get('min_words', '?')}-{limits.get('max_words', '?')}"
            state = f"{word_count(body)} words (contract {span})" if body.strip() else "not written"
            rows.append(f"- {name}: {state}")
        lint = self.lint()
        blockers = sum(1 for f in lint if f.severity == "blocker")
        rows.append(f"lint: {blockers} blocker(s), {len(lint) - blockers} other finding(s)")
        if self.last_build is not None:
            b = self.last_build
            stale = " (the draft changed since)" if self.dirty else ""
            rows.append(
                f"last build{stale}: compiled={b.compile.ok}, main pages {b.main_pages}/{c.max_main_pages}, "
                f"{len(b.gates.blockers)} gate blocker(s)"
            )
        else:
            rows.append("last build: none yet")
        return "\n".join(rows)

    @staticmethod
    def render_findings(findings: list[GateFinding], limit: int = 25) -> str:
        if not findings:
            return "no findings"
        order = {"blocker": 0, "major": 1, "minor": 2}
        rows = []
        for f in sorted(findings, key=lambda f: order.get(f.severity, 3))[:limit]:
            evidence = f" | {f.evidence[:160]}" if f.evidence else ""
            rows.append(f"- [{f.severity}] {f.gate}/{f.section}: {f.message}{evidence}")
        if len(findings) > limit:
            rows.append(f"... and {len(findings) - limit} more")
        return "\n".join(rows)

    def _note(self, event: str, **fields: Any) -> None:
        if self.log is not None:
            self.log(event, **fields)

    def _store(self, name: str, text: str) -> ToolResult:
        fenced = _FENCE.fullmatch(text.strip())
        if fenced:
            text = fenced.group(1)  # a model that wraps the whole section in a code fence
        body, report = sanitize_section(text, self.allowed_keys(name))
        if not body.strip():
            return ToolResult(f"refused: the {name} section would be empty", ok=False)
        self.sections[name] = body
        self.composer.removed[name] = list(report.removed_citations)
        self.dirty = True
        self.edits += 1
        self._note("agent.edit", section=name, words=word_count(body))
        lines = [f"saved {name}: {word_count(body)} words"]
        if report.fixes:
            lines.append("automatic fixes: " + "; ".join(report.fixes))
        if report.removed_citations:
            lines.append(
                "removed citations to keys that are not in the verified bibliography: "
                + ", ".join(sorted(set(report.removed_citations)))
            )
        lines.append("checks for this section:\n" + self.render_findings(self.lint(name)))
        return ToolResult("\n".join(lines))

    # -- tools ------------------------------------------------------------------
    def status_tool(self) -> ToolResult:
        return ToolResult(self.status())

    def read_section(self, args: SectionArg) -> ToolResult:
        body = self.sections.get(args.section, "")
        if not body.strip():
            return ToolResult(f"the {args.section} section is not written yet")
        return ToolResult(body)

    def write_section(self, args: WriteArgs) -> ToolResult:
        return self._store(args.section, args.latex)

    def edit_section(self, args: EditArgs) -> ToolResult:
        body = self.sections.get(args.section, "")
        if not body.strip():
            return ToolResult(f"the {args.section} section is not written yet; use write_section", ok=False)
        if not args.old:
            return ToolResult("old must not be empty", ok=False)
        count = body.count(args.old)
        if count == 0:
            hint = _nearest_line(body, args.old)
            return ToolResult(
                f"old text not found in {args.section}; copy it exactly from read_section"
                + (f". The closest line is:\n{hint}" if hint else ""),
                ok=False,
            )
        if count > 1 and not args.replace_all:
            return ToolResult(
                f"old text occurs {count} times in {args.section}; include more context or set replace_all", ok=False
            )
        return self._store(args.section, body.replace(args.old, args.new))

    def lint_tool(self, args: LintArgs) -> ToolResult:
        return ToolResult(self.render_findings(self.lint(args.section)))

    async def build(self) -> "BuildResult":
        self.builds += 1
        for old in self.build_root.glob("b*"):
            shutil.rmtree(old, ignore_errors=True)
        build = await self.composer.build(self.build_root / f"b{self.builds:03d}", auto_fix=False)
        self.last_build, self.dirty = build, False
        self._note("agent.build", compiled=build.compile.ok, main_pages=build.main_pages, blockers=len(build.gates.blockers))
        return build

    async def build_tool(self) -> ToolResult:
        missing = self.missing()
        if missing:
            return ToolResult("cannot build yet; these sections are not written: " + ", ".join(missing), ok=False)
        build = await self.build()
        c = self.composer
        lines = [
            f"compiled: {build.compile.ok}",
            f"main-text pages: {build.main_pages} (limit {c.max_main_pages})",
        ]
        if not build.compile.ok:
            for err in build.compile.errors[:3]:
                lines.append(f"LaTeX error in {err.file}:{err.line}: {err.message}")
            lines.append("log tail:\n" + build.compile.log_tail[-800:])
        lines.append("gate findings:\n" + self.render_findings(build.gates.findings))
        return ToolResult("\n".join(lines), ok=build.compile.ok)

    def set_title(self, args: TitleArgs) -> ToolResult:
        title = re.sub(r"[\\{}$^_#&%~\"]", "", args.title).strip()
        if not title:
            return ToolResult("the title is empty", ok=False)
        if len(title.split()) > 16:
            return ToolResult(f"the title has {len(title.split())} words; keep it to at most 14", ok=False)
        self.composer.title = title[:180]
        self.title_set = self.dirty = True
        return ToolResult(f"title set: {self.composer.title}")

    def lookup_numbers(self, args: QueryArgs) -> ToolResult:
        terms = [t for t in re.split(r"[\s,]+", args.query.lower()) if t]
        rows = [e for e in self.composer.registry.entries if all(t in e.label.lower() for t in terms)]
        if not rows:
            return ToolResult(
                "no registered value matches; labels look like '<variant>.<metric>.mean', "
                "'<proposed>-vs-<baseline>.<metric>.diff', or 'setup:design'"
            )
        shown = [f"{e.label} = {e.value:.6g} ({e.kind})" for e in rows[:40]]
        more = f"\n... {len(rows) - 40} more; narrow the query" if len(rows) > 40 else ""
        return ToolResult(
            "Registered values (state them rounded as in the results brief):\n" + "\n".join(shown) + more
        )

    def search_evidence(self, args: QueryArgs) -> ToolResult:
        items = self.memory.search(args.query, kinds=["evidence"], run_id=self.run_id, limit=8)
        if not items:
            return ToolResult("no evidence matches")
        return ToolResult("\n".join(f"- [{item.id}] {item.render()}" for item in items))

    def read_material(self, args: MaterialArgs) -> ToolResult:
        text = getattr(self.materials, args.name)
        if not text.strip():
            return ToolResult(f"this run has no {args.name}")
        return ToolResult(truncate_tokens(text, 8000))

    # -- tool sets ----------------------------------------------------------------
    def read_tools(self) -> list[Tool]:
        return [
            Tool("paper_status", "Show the title, each section's word count against its contract, the lint "
                 "summary, and the last build.", self.status_tool, effect="read"),
            Tool("read_section", "Return a section's current LaTeX.", self.read_section, SectionArg, effect="read"),
            Tool("lookup_numbers", "Search the registry of computed values the paper may state (results, "
                 "intervals, p-values, setup numbers) by words in their labels, e.g. 'proposed accuracy' or 'vs'.",
                 self.lookup_numbers, QueryArgs, effect="read"),
            Tool("search_evidence", "Search this run's evidence: quoted findings of cited papers and result lines.",
                 self.search_evidence, QueryArgs, effect="read"),
            Tool("read_material", "Read the full experiment design or the experiment agents' reflection "
                 "(the context holds excerpts only).", self.read_material, MaterialArgs, effect="read"),
            Tool("lint", "Run every gate that needs no compilation (numbers, citations, structure, placeholders, "
                 "internal terms) on one section or the whole paper.", self.lint_tool, LintArgs, effect="check"),
        ]

    def edit_tools(self) -> list[Tool]:
        return [
            Tool("write_section", "Write or replace a whole section. The text is sanitized, citations to "
                 "unknown keys are removed, and the section's checks are returned.", self.write_section, WriteArgs,
                 effect="edit"),
            Tool("edit_section", "Replace one exact passage of a section (copy it from read_section). Prefer this "
                 "to rewriting a whole section when changing part of it. The section's checks are returned.",
                 self.edit_section, EditArgs, effect="edit"),
            Tool("set_title", "Set the paper's title.", self.set_title, TitleArgs, effect="edit"),
            Tool("build_paper", "Compile the paper and run every gate: LaTeX errors, page limit, undefined "
                 "references, numbers, citations, structure. Run it after your edits, before you finish.",
                 self.build_tool, effect="check"),
        ]


def _nearest_line(body: str, old: str) -> str:
    """The line of ``body`` sharing the most words with ``old``'s first line, to help fix a near miss."""
    target = set(re.findall(r"\w+", old.splitlines()[0].lower())) if old.strip() else set()
    if not target:
        return ""
    best, score = "", 0
    for line in body.splitlines():
        overlap = len(target & set(re.findall(r"\w+", line.lower())))
        if overlap > score:
            best, score = line, overlap
    return best[:400] if score >= max(2, len(target) // 3) else ""
