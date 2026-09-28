"""Simulated peer review aligned with the Stanford Agentic Reviewer's dimensions.

The public description of the Stanford Agentic Reviewer (paperreview.ai)
scores seven dimensions -- originality, importance of the research question,
whether claims are supported by evidence, soundness of experiments, clarity of
writing, value to the research community, and contextualization relative to
prior work -- and combines them into an ICLR-style score. Tyche's panel
scores the same seven dimensions with three reviewer lenses plus a fidelity
auditor. The composite below is an unweighted mean chosen by us; it is not
the reviewer's own regression and should only be read as a relative signal
between drafts of the same paper.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, Field

from tyche.llm import LLMClient, LLMError, complete_json, schema_hint
from tyche.prompts import load_prompt
from tyche.textutil import truncate_tokens

DIMENSIONS = (
    "originality",
    "importance",
    "claims_supported",
    "experimental_soundness",
    "clarity",
    "community_value",
    "contextualization",
)
SECTIONS = ("abstract", "introduction", "related_work", "method", "experiments", "analysis", "conclusion", "general")

PERSONAS = {
    "rigor": (
        "empirical rigor. Scrutinize whether the experiments test the hypotheses, whether baselines are fair, "
        "whether statistics and uncertainty are reported and interpreted correctly, and whether any claim "
        "outruns the evidence."
    ),
    "positioning": (
        "novelty and positioning. Scrutinize what is genuinely new, whether the closest prior work is discussed "
        "and contrasted, and whether the research question matters to the agent community."
    ),
    "clarity": (
        "clarity and impact. Scrutinize whether a busy reader can extract the problem, the idea, the evidence, "
        "and the takeaway quickly, and whether practitioners would find the result usable."
    ),
}


class Scores(BaseModel):
    originality: int = Field(ge=1, le=10)
    importance: int = Field(ge=1, le=10)
    claims_supported: int = Field(ge=1, le=10)
    experimental_soundness: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    community_value: int = Field(ge=1, le=10)
    contextualization: int = Field(ge=1, le=10)


class ReviewFinding(BaseModel):
    section: str
    severity: Literal["blocker", "major", "minor"]
    dimension: str
    quote: str
    problem: str
    fix: str
    close_criterion: str


class PriorRuling(BaseModel):
    id: str
    status: Literal["resolved", "still_open", "wontfix_accepted"]
    note: str = ""


class ReviewOutput(BaseModel):
    scores: Scores
    overall: int = Field(ge=1, le=10)
    confidence: int = Field(ge=1, le=5)
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=8)
    prior_rulings: list[PriorRuling] = Field(default_factory=list)


class AuditOutput(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=8)


_ALNUM = re.compile(r"[^a-z0-9]+")


def _squash(text: str) -> str:
    return _ALNUM.sub("", text.lower())


def quote_in(quote: str, haystack_squashed: str) -> bool:
    q = _squash(quote)
    return len(q) >= 15 and q in haystack_squashed


_DOWNGRADE = {"blocker": "major", "major": "minor", "minor": None}


@dataclass
class PanelRound:
    reviews: dict[str, dict[str, Any]]
    dimension_means: dict[str, float]
    composite: float
    overall_mean: float
    findings: list[dict[str, Any]]
    rulings: list[dict[str, Any]] = field(default_factory=list)
    dropped_findings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_findings(
    raw: list[ReviewFinding], source: str, paper_squashed: str
) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in raw:
        finding = item.model_dump()
        finding["source"] = source
        finding["section"] = finding["section"] if finding["section"] in SECTIONS else "general"
        if finding["dimension"] not in DIMENSIONS:
            finding["dimension"] = "clarity"
        finding["quote_verified"] = quote_in(finding["quote"], paper_squashed)
        if not finding["quote_verified"]:
            lower = _DOWNGRADE[finding["severity"]]
            if lower is None:
                dropped += 1
                continue
            finding["severity"] = lower
        kept.append(finding)
    return kept, dropped


class ReviewPanel:
    def __init__(
        self,
        llm: LLMClient,
        *,
        reviewers: list[str],
        samples: int = 1,
        budget: int = 24000,
        auditor: bool = True,
        tools: list | None = None,
        agent_settings=None,
        transcripts: Path | None = None,
        log=None,
    ):
        unknown = [r for r in reviewers if r not in PERSONAS]
        if unknown:
            raise ValueError(f"unknown reviewer persona(s): {unknown}")
        self.llm = llm
        self.reviewers = reviewers
        self.samples = max(1, samples)
        self.budget = budget
        self.auditor = auditor
        # Read-only paper tools: with them, each reviewer and the auditor is an agent session that can
        # check numbers and cited evidence before reporting (see tyche.agent); without them, one call each.
        self.tools = list(tools or [])
        self.agent_settings = agent_settings
        self.transcripts = transcripts
        self.log = log or (lambda *a, **k: None)
        self._round = 0

    async def _ask(self, system: str, task: str, schema: type[BaseModel], purpose: str) -> BaseModel:
        """One reviewer's report: from an agent session with tools when configured, else one call."""
        if not self.tools:
            return await complete_json(self.llm, system=system, user=task, schema=schema, purpose=purpose)
        from tyche.agent.session import AgentSession
        from tyche.agent.tools import Tool, ToolResult

        class SubmitArgs(BaseModel):
            report: dict = Field(description="Your report as one JSON object.")

        def submit(args: SubmitArgs) -> ToolResult:
            try:
                report = schema.model_validate(args.report)
            except Exception as exc:  # noqa: BLE001 - validation errors go back to the reviewer
                return ToolResult(f"the report does not validate: {str(exc)[:1500]}", ok=False)
            return ToolResult("report received", data=report)

        settings = self.agent_settings
        role = purpose.split(":", 1)[-1]
        session = AgentSession(
            self.llm,
            name=f"reviewer_{role}",
            # Identical for every reviewer and the auditor, so the provider caches the paper once.
            instructions=load_prompt("review_common") + "\n\n" + load_prompt("agent_reviewer"),
            tools=[*self.tools, Tool("submit", "Submit your report; it ends your task. The report must validate "
                                     "against the schema in your task.", submit, SubmitArgs, effect="result",
                                     ends_session=True)],
            policy=settings.policy("read_only") if settings else None,
            context=system,
            purpose=f"agent:{purpose}",
            max_turns=settings.turns("review") if settings else 6,
            transcript=self.transcripts / f"round{self._round}_{role}.jsonl" if self.transcripts else None,
            log=self.log,
        )
        outcome = await session.run(
            task + "\n\n<output_schema>\n" + schema_hint(schema) + "\n</output_schema>\nCheck what you need with "
            "the tools, then call submit with the report."
        )
        if outcome.result is not None:
            return outcome.result
        # The session ended without a valid report; ask once more without tools rather than lose the review.
        self.log("review.agent_fallback", reviewer=role, status=outcome.status)
        try:
            return await complete_json(self.llm, system=system, user=task, schema=schema, purpose=purpose)
        except LLMError as exc:
            raise LLMError(f"reviewer {role} produced no valid report ({outcome.status}): {exc}") from exc

    async def review(
        self,
        *,
        paper_text: str,
        sections: dict[str, str],
        uncited_related: list[dict[str, Any]],
        prior_findings: list[dict[str, Any]],
        results_brief: str,
        cited_evidence: dict[str, str],
        experiment_reflection: str = "",
    ) -> PanelRound:
        self._round += 1
        paper = truncate_tokens(paper_text, int(self.budget * 0.7))
        squashed = _squash(paper_text) + _squash(" ".join(sections.values()))
        prior = [
            {k: f[k] for k in ("id", "section", "severity", "problem", "fix", "close_criterion", "response") if k in f}
            for f in prior_findings
        ]
        # Per-run context first (it is the same in every round), then the paper of this round.
        base_user = (
            "<retrieved_related_work>\n" + json.dumps(uncited_related[:15], ensure_ascii=False, indent=1)
            + "\n</retrieved_related_work>\n"
            "<paper_text>\n" + paper + "\n</paper_text>\n"
        )
        if prior:
            base_user += "<prior_findings>\n" + json.dumps(prior, ensure_ascii=False, indent=1) + "\n</prior_findings>\n"
        # One prefix for the whole panel: a neutral preamble, then the paper and its review context.
        # Every reviewer and the auditor send it byte-identically as the system prompt (the JSON
        # schema and each role's instructions come in the user turn), so a provider's prefix cache
        # serves the paper to every call after the first; request parameters are the same for all
        # of them (one reviewer role).
        shared = load_prompt("review_common") + "\n\n" + base_user
        reviews: dict[str, dict[str, Any]] = {}
        findings: list[dict[str, Any]] = []
        rulings: list[dict[str, Any]] = []
        dropped = 0
        per_dim: dict[str, list[float]] = {d: [] for d in DIMENSIONS}
        overall: list[float] = []
        for persona in self.reviewers:
            for sample in range(self.samples):
                name = persona if self.samples == 1 else f"{persona}#{sample + 1}"
                # Instructions precede the lens, so they are cached for every persona after the first.
                out = await self._ask(
                    shared,
                    load_prompt("review_system")
                    + "\n\n<reviewer_lens>\n"
                    + PERSONAS[persona]
                    + "\n</reviewer_lens>\nReview the paper through this lens.",
                    ReviewOutput,
                    f"review:{persona}",
                )
                reviews[name] = out.model_dump()
                for dim in DIMENSIONS:
                    per_dim[dim].append(float(getattr(out.scores, dim)))
                overall.append(float(out.overall))
                kept, lost = normalize_findings(out.findings, name, squashed)
                findings += kept
                dropped += lost
                rulings += [dict(r.model_dump(), reviewer=name) for r in out.prior_rulings]
        if self.auditor:
            cited = "\n".join(f"[{key}] {text}" for key, text in cited_evidence.items())
            # The auditor shares the reviewers' cached prefix. It also needs the LaTeX: only there do
            # \citep keys appear, and it matches them against the evidence for each key.
            audit_user = (
                load_prompt("auditor_system")
                + "\n\n<paper_latex>\n"
                + truncate_tokens("\n\n".join(f"%% {n}\n{b}" for n, b in sections.items()), int(self.budget * 0.5))
                + "\n</paper_latex>\n<results_brief>\n"
                + results_brief
                + "\n</results_brief>\n<cited_evidence>\n"
                + truncate_tokens(cited, int(self.budget * 0.3))
                + "\n</cited_evidence>"
            )
            if experiment_reflection:
                audit_user += "\n<experiment_reflection>\n" + experiment_reflection + "\n</experiment_reflection>"
            audit = await self._ask(shared, audit_user, AuditOutput, "review:auditor")
            kept, lost = normalize_findings(audit.findings, "auditor", squashed)
            findings += kept
            dropped += lost
        dim_means = {d: round(mean(v), 3) for d, v in per_dim.items() if v}
        composite = round(mean(dim_means.values()), 3) if dim_means else 0.0
        return PanelRound(
            reviews=reviews,
            dimension_means=dim_means,
            composite=composite,
            overall_mean=round(mean(overall), 3) if overall else 0.0,
            findings=findings,
            rulings=rulings,
            dropped_findings=dropped,
        )
