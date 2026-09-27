import json
import subprocess
from pathlib import Path

from tyche.analysis.registry import NumberRegistry
from tyche.config import TycheConfig
from tyche.trace import (
    build_claim_map,
    capture_environment,
    claim_map_for_run,
    lineage_graph,
    plain_text,
    revision_history,
    split_sentences,
    upstream,
)
from tyche.trace import environment
from tyche.trace.claims import parse_label

from .conftest import needs_latex

PAPERS = [
    {"key": "fixture2024alpha", "title": "Alpha Ledgers: A Fixture Study", "authors": ["Ada Fixture"], "year": 2024,
     "arxiv_id": "0000.00011", "url": "https://arxiv.org/abs/0000.00011", "doi": ""},
    {"key": "testcase2025beta", "title": "Beta Windows: Testcase Notes", "authors": ["Bo Testcase"], "year": 2025,
     "arxiv_id": "0000.00012", "url": "", "doi": ""},
]
CARDS = [
    {"key": "fixture2024alpha", "memory_id": "evi-0000", "claim": "The work reports: ledgers keep corrections.",
     "quote": "Ledgers keep corrections linked to the facts they supersede"},
]


def _registry() -> NumberRegistry:
    reg = NumberRegistry()
    reg.add(0.8123, "proposed.accuracy")
    reg.add(0.1, "proposed.accuracy.ci_halfwidth", "derived")
    reg.add(-0.0667, "proposed-vs-window.accuracy.diff_ci_low", "derived")
    reg.add(0.1, "proposed-vs-window.accuracy.diff", "derived")
    reg.add(60, "proposed.accuracy.n", "setup")
    reg.add(95.0, "confidence.percent", "setup")
    reg.add(1024, "setup:design", "setup")
    return reg


# -- sentence splitting ------------------------------------------------------------
def test_split_sentences_handles_abbreviations_decimals_citations_and_math():
    latex = (
        "We report 0.812 accuracy, e.g. on the Fixture split, as Testcase et al. \\citep{fixture2024alpha} note. "
        "% a comment with 99.9 and \\citep{ghost2099x}\n"
        "The gain is 12.5\\% (Fig.~\\ref{fig:x}) vs. the baseline; cf. Sec. 2 for details, i.e. the full run. "
        "Inline math $x = 3.14. Y$ stays whole! Is it robust? Yes, etc. Done.\n\n"
        "\\paragraph{Results.} \\textbf{Setup.} We use \\emph{sixty} items~\\citet[p.~3]{testcase2025beta}."
    )
    sentences = split_sentences(latex)
    assert [plain_text(s) for s in sentences] == [
        "We report 0.812 accuracy, e.g. on the Fixture split, as Testcase et al. [fixture2024alpha] note.",
        "The gain is 12.5% (Fig. fig:x) vs. the baseline; cf. Sec. 2 for details, i.e. the full run.",
        "Inline math x = 3.14. Y stays whole!",
        "Is it robust?",
        "Yes, etc. Done.",
        "Results.",
        "Setup.",
        "We use sixty items [testcase2025beta].",
    ]
    assert all("ghost2099x" not in s and "99.9" not in s for s in sentences)


def test_display_math_lists_and_floats():
    latex = r"""Scores follow
\begin{equation}
s = 0.5 \cdot a + b .
\end{equation}
The next sentence starts here.
\begin{itemize}
\item A first contribution \citep{fixture2024alpha}.
\item A second one without a period
\end{itemize}
\begin{table}[t]
\centering
\caption{Accuracy with 95\% intervals. Values are means.}
\label{tab:main}
\begin{tabular}{lc}
proposed & 0.999 \\
\end{tabular}
\end{table}
A standalone \begin{tabular}{c} 77.7 \end{tabular} tail."""
    plain = [plain_text(s) for s in split_sentences(latex)]
    assert plain == [
        "Scores follow s = 0.5 · a + b.",
        "The next sentence starts here.",
        "A first contribution [fixture2024alpha].",
        "A second one without a period",
        "Accuracy with 95% intervals.",
        "Values are means.",
        "A standalone",
        "tail.",
    ]
    assert not any("0.999" in p or "77.7" in p or "tab:main" in p for p in plain)


# -- claim map ------------------------------------------------------------------------
def test_numbers_match_with_percent_and_sign_and_trace_to_their_source():
    sections = {
        "experiments": "The proposed variant reaches 81.2\\% accuracy (95\\% CI -0.067 to 0.100, n = 60) "
        "with a budget of 1,024 tokens. A drop of -0.812 is not supported."
    }
    analysis = {
        "variants": {"proposed": {"accuracy": {}}, "window": {"accuracy": {}}},
        "metrics": ["accuracy"],
        "comparisons": [{"metric": "accuracy", "proposed": "proposed", "baseline": "window", "n": 60, "diff": 0.1,
                         "ci_low": -0.0667, "ci_high": 0.26, "p_value": 0.3, "relative": 14.2, "better": True}],
    }
    result = build_claim_map(
        sections, registry=_registry(), papers=[], cards=[], analysis=analysis,
        metrics_files={"proposed": "proposed.metrics.json", "window": "window.metrics.json"},
    )
    first, second = result["claims"]
    numbers = {n["text"]: n for n in first["numbers"]}
    assert list(numbers) == ["81.2", "95", "-0.067", "0.100", "60", "1024"]
    acc = numbers["81.2"]
    assert acc["percent"] and acc["match"]["label"] == "proposed.accuracy"
    assert acc["match"] | {"value": None} == {
        "label": "proposed.accuracy", "value": None, "kind": "result", "variant": "proposed", "metric": "accuracy",
        "stat": "value", "comparison": None, "source": "analysis", "metrics_file": "proposed.metrics.json",
    }
    low = numbers["-0.067"]["match"]
    assert low["stat"] == "diff_ci_low" and low["variant"] is None and low["metrics_file"] is None
    assert low["comparison"]["baseline"] == "window" and low["comparison"]["diff"] == 0.1
    assert low["comparison"]["metrics_files"] == ["proposed.metrics.json", "window.metrics.json"]
    # The gate's first match is kept; every other value the token rounds to is listed.
    assert numbers["0.100"]["match"]["label"] == "proposed.accuracy.ci_halfwidth"
    assert numbers["0.100"]["alternatives"] == ["proposed-vs-window.accuracy.diff"]
    assert numbers["95"]["match"]["stat"] == "confidence.percent"
    assert numbers["1024"]["match"]["source"] == "setup" and numbers["1024"]["match"]["label"] == "setup:design"
    assert first["status"] == "verified" and first["kind"] == "numeric"
    # A minus sign must match the registered sign.
    assert second["numbers"][0]["text"] == "-0.812" and second["numbers"][0]["match"] is None
    assert second["status"] == "unverified"


def test_parse_label_grammar_with_and_without_analysis():
    assert parse_label("proposed.accuracy.ci_low") == {
        "variant": "proposed", "metric": "accuracy", "stat": "ci_low", "comparison": None, "source": "analysis",
    }
    assert parse_label("proposed.accuracy")["stat"] == "value"
    cmp = parse_label("proposed-vs-full_context.tokens.p_value")
    assert cmp["stat"] == "p_value" and cmp["comparison"]["baseline"] == "full_context"
    assert parse_label("setup:plan")["source"] == "setup"
    assert parse_label("count.variants")["stat"] == "count.variants"
    dotted = {"variants": {"model.v2": {"rouge.l": {}}}, "metrics": ["rouge.l"]}
    assert parse_label("model.v2.rouge.l.mean", dotted) == {
        "variant": "model.v2", "metric": "rouge.l", "stat": "mean", "comparison": None, "source": "analysis",
    }


def test_citation_status_verified_weak_unverified_and_stats():
    sections = {
        "related_work": (
            "Ledgers keep corrections \\citep{fixture2024alpha}. Windows forget \\citet{testcase2025beta}. "
            "Ghost work exists \\citep[e.g.][]{fixture2024alpha, nobody2099ghost}. Plain prose has no claim."
        ),
        "abstract": "We reach 81.2\\% accuracy \\citealp{fixture2024alpha}.",
    }
    result = build_claim_map(sections, registry=_registry(), papers=PAPERS, cards=CARDS)
    claims = result["claims"]
    assert [c["id"] for c in claims] == ["C001", "C002", "C003", "C004"]
    assert [(c["section"], c["kind"], c["status"]) for c in claims] == [
        ("abstract", "mixed", "verified"),
        ("related_work", "citation", "verified"),
        ("related_work", "citation", "weak"),
        ("related_work", "citation", "unverified"),
    ]
    alpha = claims[1]["citations"][0]
    assert alpha == {
        "key": "fixture2024alpha", "known": True, "title": "Alpha Ledgers: A Fixture Study", "year": 2024,
        "url": "https://arxiv.org/abs/0000.00011",
        "cards": [{"claim": "The work reports: ledgers keep corrections.",
                   "quote": "Ledgers keep corrections linked to the facts they supersede"}],
        "carded": True,
    }
    beta = claims[2]["citations"][0]
    assert beta["known"] and not beta["carded"] and beta["url"] == "https://arxiv.org/abs/0000.00012"
    ghost = claims[3]["citations"][1]
    assert ghost == {"key": "nobody2099ghost", "known": False, "title": None, "year": None, "url": None,
                     "cards": [], "carded": False}
    assert claims[3]["sentence"] == "Ghost work exists [fixture2024alpha; nobody2099ghost]."
    assert result["stats"] == {
        "sentences": 5, "claims": 4, "verified": 2, "weak": 1, "unverified": 1, "numbers": 1, "numbers_matched": 1,
        "citations": 5, "citations_known": 4, "citations_carded": 3,
    }


def test_claim_ids_follow_paper_order_and_are_stable():
    sections = {
        "zeta_notes": "Extra note \\citep{fixture2024alpha}.",
        "conclusion": "We reach 81.2\\% accuracy.",
        "experiments": "Accuracy is 0.812 on 60 items.",
        "experiments_floats": "\\begin{table}\\caption{Means over 60 items.}\\end{table}",
        "abstract": "Accuracy is 0.812.",
        "method": "No claims here.",
    }
    first = build_claim_map(sections, registry=_registry(), papers=PAPERS, cards=CARDS)
    again = build_claim_map(dict(reversed(list(sections.items()))), registry=_registry(), papers=PAPERS, cards=CARDS)
    assert first == again
    assert [(c["id"], c["section"]) for c in first["claims"]] == [
        ("C001", "abstract"), ("C002", "experiments_floats"), ("C003", "experiments"), ("C004", "conclusion"),
        ("C005", "zeta_notes"),
    ]
    json.dumps(first)  # JSON-ready


def test_claim_map_for_run_without_paper_returns_none(workspace):
    workspace.save_json("plan", {"working_title": "Fixture"}, stage="plan")
    assert claim_map_for_run(workspace.run_dir) is None
    assert revision_history(workspace.run_dir)["rounds"] == []


def test_claim_map_for_run_uses_draft_and_bibliography(workspace):
    ws = workspace
    ws.save_json("numbers", _registry().to_list(), stage="analysis")
    ws.save_json("source_manifest", {"papers": PAPERS[:1], "evidence_cards": CARDS}, stage="survey")
    bib = "@article{testcase2025beta,\n  title = {Beta {Windows}: Testcase Notes},\n  year = {2025},\n  eprint = {0000.00012}\n}\n"
    (ws.run_dir / "write").mkdir(exist_ok=True)
    (ws.run_dir / "write" / "refs.bib").write_text(bib, encoding="utf-8")
    ws.save_json("draft", {"title": "T", "sections": {"abstract": "Reaches 0.812 \\citep{testcase2025beta}."}}, stage="write")
    result = claim_map_for_run(ws.run_dir)
    assert result["sources"]["sections"] == "draft@v1" and result["sources"]["bibliography"] == "write/refs.bib"
    claim = result["claims"][0]
    # Admitted during review: verified bibliography entry without an evidence card.
    assert claim["status"] == "weak" and claim["citations"][0]["title"] == "Beta Windows: Testcase Notes"
    assert claim["citations"][0]["year"] == 2025 and claim["citations"][0]["url"] == "https://arxiv.org/abs/0000.00012"


# -- revision history -----------------------------------------------------------------
DRAFT = {"abstract": "We study ledgers.", "analysis": "Old mechanism claim.\n\nLimitations are listed."}
ROUND1 = {"abstract": "We study ledgers.", "analysis": "The pattern is descriptive.\n\nLimitations are listed."}
ROUND2 = {"abstract": "We study provenance ledgers.", "analysis": ROUND1["analysis"]}


def _review_run(ws, *, builds: bool, stale: bool = False):
    ws.save_json("draft", {"title": "T", "sections": DRAFT, "removed_citations": {}}, stage="write")
    rounds = []
    for n, accepted, revised, found, composite, delta in (
        (0, True, None, None, 5.0, None),
        (1, True, ["analysis"], ["F001", "F009"], 6.0, 1.0),
        (2, False, ["abstract"], ["F002"], 5.5, -0.5),
    ):
        row = {"round": n, "accepted": accepted, "composite": composite, "blockers": 0,
               "build": {"build_dir": str(ws.run_dir / "review" / f"build_r{n}"), "repairs": [], "trims": []}}
        if n:
            row.update(sections_revised=revised, findings_addressed=found, delta=delta)
        rounds.append(row)
    ledger = {"reflag_cap": 2, "entries": [
        {"id": "F001", "round_opened": 0, "source": "rigor", "severity": "major", "dimension": "claims_supported",
         "section": "analysis", "quote": "Old mechanism claim", "problem": "Untested mechanism.", "fix": "Narrow it.",
         "close_criterion": "Narrowed.", "status": "resolved", "reflags": 0, "response": "fixed: narrowed",
         "history": ["r0: opened by rigor", "r1: writer fixed", "r1: revision accepted (composite +1.00)"],
         "revision_accepted": True, "score_delta": 1.0},
        {"id": "F002", "round_opened": 1, "source": "clarity", "severity": "minor", "dimension": "clarity",
         "section": "abstract", "quote": "", "problem": "Vague subject.", "fix": "Name it.", "close_criterion": "Named.",
         "status": "open", "reflags": 0, "response": "", "history": ["r1: opened by clarity", "r2: revision rejected"],
         "revision_accepted": False, "score_delta": -0.5},
    ]}
    inputs = [ws.latest("draft").id]
    ws.save_json("paper", {"title": "T", "sections": ROUND1}, stage="review", inputs=inputs)
    ws.save_json("ledger", ledger, stage="review", inputs=inputs)
    ws.save_json("review_rounds", rounds, stage="review", inputs=inputs)
    # A later rewrite must not be mistaken for the draft this review started from.
    ws.save_json("draft", {"title": "T", "sections": {"abstract": "Rewritten.", "analysis": "Rewritten."}}, stage="write")
    if builds:
        for n, sections in enumerate((DRAFT, ROUND1, ROUND2)):
            target = ws.run_dir / "review" / f"build_r{n}" / "sections"
            target.mkdir(parents=True)
            for name, text in {**sections, "experiments_floats": "floats", "ai_statement": "stmt"}.items():
                (target / f"{name}.tex").write_text(text.strip() + "\n", encoding="utf-8")
        written = rounds if not stale else rounds[:2]
        (ws.run_dir / "review" / "rounds.json").write_text(json.dumps(written), encoding="utf-8")


def test_revision_history_from_artifacts_only(workspace):
    _review_run(workspace, builds=False)
    history = revision_history(workspace.run_dir)
    assert (history["draft"], history["paper"], history["ledger"]) == ("draft@v1", "paper@v1", "ledger@v1")
    assert history["text_source"] == "artifacts"
    r0, r1, r2 = history["rounds"]
    assert (r0["round"], r0["sections"], r0["note"]) == (0, [], "review of the written draft")
    assert r1["accepted"] and r1["composite"] == 6.0 and r1["delta"] == 1.0 and r1["text_source"] == "artifacts"
    assert r1["sections_revised"] == ["analysis"]
    (change,) = r1["sections"]
    assert change["name"] == "analysis" and (change["before_words"], change["after_words"]) == (6, 7)
    assert "-Old mechanism claim." in change["diff"] and "+The pattern is descriptive." in change["diff"]
    assert change["diff"].startswith("--- analysis (before)\n+++ analysis (round 1)")
    found = {f["id"]: f for f in r1["findings"]}
    assert found["F001"]["status"] == "resolved" and found["F001"]["response"] == "fixed: narrowed"
    assert found["F001"]["round_history"] == ["r1: writer fixed", "r1: revision accepted (composite +1.00)"]
    assert found["F009"]["in_ledger"] is False and found["F009"]["status"] is None
    assert not r2["accepted"] and r2["sections"] == [] and r2["note"] == "candidate not retained"
    assert r2["findings"][0]["round_history"] == ["r2: revision rejected"]
    assert [s["name"] for s in history["overall"]] == ["analysis"]


def test_revision_history_uses_matching_review_builds(workspace):
    _review_run(workspace, builds=True)
    history = revision_history(workspace.run_dir)
    assert history["text_source"] == "review_builds"
    r0, r1, r2 = history["rounds"]
    assert r0["sections"] == [] and r1["text_source"] == "review_build"
    assert [s["name"] for s in r1["sections"]] == ["analysis"]
    # The rejected candidate is still on disk, so its changes are shown against the kept text.
    assert [s["name"] for s in r2["sections"]] == ["abstract"]
    assert "+We study provenance ledgers." in r2["sections"][0]["diff"]
    assert r2["note"] == "candidate rejected; the paper kept the previous text"


def test_revision_history_ignores_stale_review_builds(workspace):
    _review_run(workspace, builds=True, stale=True)
    history = revision_history(workspace.run_dir)
    assert history["text_source"] == "artifacts"
    assert history["rounds"][2]["note"] == "candidate not retained"
    assert [s["name"] for s in history["rounds"][1]["sections"]] == ["analysis"]


# -- lineage --------------------------------------------------------------------------
def test_lineage_graph_and_upstream(workspace):
    ws = workspace
    ws.save_json("plan", {"v": 1}, stage="plan", inputs=["operator_notes@v1"])
    ws.save_json("plan", {"v": 2}, stage="plan")
    ws.save_json("refs_bib", {}, stage="survey", inputs=["plan@v2"])
    ws.save_json("draft", {}, stage="write", inputs=["plan@v2", "refs_bib@v1", "numbers@v1"])
    ws.save_json("numbers", [], stage="analysis", inputs=["experiment_results@v1"])
    with ws.provenance_path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": "paper@v1", "name": "pa')  # a line still being written by a live run
    graph = lineage_graph(ws.run_dir)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert list(nodes) == ["plan@v1", "plan@v2", "refs_bib@v1", "draft@v1", "numbers@v1"]
    assert nodes["plan@v1"]["latest"] is False and nodes["plan@v2"]["latest"] is True
    assert nodes["plan@v1"]["path"] == "artifacts/plan/v1.json" and len(nodes["plan@v1"]["sha256"]) == 64
    assert {"from": "plan@v1", "to": "plan@v2", "kind": "parent"} in graph["edges"]
    assert {"from": "refs_bib@v1", "to": "draft@v1", "kind": "input"} in graph["edges"]
    assert graph["stages"] == ["plan", "survey", "analysis", "write"]
    assert graph["missing"] == ["experiment_results@v1", "operator_notes@v1"]
    up = upstream(graph, "draft@v1")
    assert up[:3] == ["plan@v2", "refs_bib@v1", "numbers@v1"]
    assert set(up) == {"plan@v2", "refs_bib@v1", "numbers@v1", "plan@v1", "experiment_results@v1", "operator_notes@v1"}
    assert upstream(graph, "plan@v1") == ["operator_notes@v1"]
    assert upstream(graph, "nothing@v9") == []


# -- environment ------------------------------------------------------------------------
SECRET = "sk-fixture-secret-0000abcd"


def test_capture_environment_is_offline_and_never_leaks_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("API_KEY", SECRET)
    monkeypatch.setenv("TYCHE_FIXTURE_TOKEN", SECRET + "-other")
    (tmp_path / "pyproject.toml").write_text(
        'dependencies = ["openjiuwen @ git+https://gitcode.com/openJiuwen/agent-core.git@0123456789abcdef0123456789abcdef01234567"]\n',
        encoding="utf-8",
    )
    present = {"pdflatex", "bibtex", "pdftotext", "git"}
    monkeypatch.setattr(environment.shutil, "which", lambda tool: f"/fixture/bin/{tool}" if tool in present else None)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 5
        tool = Path(args[0]).name
        if tool == "pdftotext":
            raise subprocess.TimeoutExpired(args, 5)
        replies = {
            "pdflatex": "pdfTeX 3.14 (Fixture TeX)\nmore",
            "bibtex": f"\nBibTeX 0.99 fixture {SECRET}\n",
            "HEAD": "0123456789abcdef0123456789abcdef01234567\n",
            "--abbrev-ref": "fixture-branch\n",
            "--porcelain": " M tyche/fixture.py\n",
        }
        key = tool if tool != "git" else next(a for a in ("--abbrev-ref", "--porcelain", "HEAD") if a in args)
        return subprocess.CompletedProcess(args, 0, stdout=replies[key], stderr="")

    monkeypatch.setattr(environment.subprocess, "run", fake_run)
    config = TycheConfig.load(overrides=[f"models.default.api_base=https://fixture.invalid/v1?key={SECRET}"], env={})
    snap = capture_environment(config=config, repo_root=tmp_path)
    text = json.dumps(snap)
    assert SECRET not in text
    assert snap["tools"] == {"pdflatex": "pdfTeX 3.14 (Fixture TeX)", "bibtex": "BibTeX 0.99 fixture [redacted]",
                             "latexmk": None, "pdftotext": None}
    assert snap["git"] == {"commit": "0123456789abcdef0123456789abcdef01234567", "branch": "fixture-branch",
                           "dirty": True}
    assert snap["openjiuwen"]["pinned_commit"] == "0123456789abcdef0123456789abcdef01234567"
    writer = snap["models"]["writer"]
    assert writer["api_key_env"] == "API_KEY" and writer["api_base"] == "https://fixture.invalid/v1?key=[redacted]"
    assert set(snap["models"]) == {"planner", "writer", "reviewer", "experiments", "subject"}
    assert snap["python"]["version"] and snap["platform"]["system"] and snap["captured_at"].endswith("+00:00")
    assert snap["tyche"]["version"] and snap["config_digest"] == config.digest()
    assert not any("latexmk" in str(a[0]) for a in calls)


def test_capture_environment_without_tools_repo_or_config(monkeypatch, tmp_path):
    monkeypatch.setattr(environment.shutil, "which", lambda tool: None)

    def broken_run(*args, **kwargs):
        raise OSError("no processes in this fixture")

    monkeypatch.setattr(environment.subprocess, "run", broken_run)
    snap = capture_environment(repo_root=tmp_path / "not-a-repo")
    assert snap["tools"] == dict.fromkeys(("pdflatex", "bibtex", "latexmk", "pdftotext"))
    assert snap["git"] is None and snap["models"] is None and snap["openjiuwen"]["pinned_commit"] is None


# -- integration ---------------------------------------------------------------------------
@needs_latex
async def test_trace_views_of_the_selftest_run(tmp_path):
    from tyche.selftest import run_selftest

    summary = await run_selftest(root=tmp_path, echo=lambda *a: None)
    assert summary["ok"], summary
    run_dir = tmp_path / "runs" / "selftest"
    claims = claim_map_for_run(run_dir)
    stats = claims["stats"]
    assert stats["claims"] > 0 and stats["numbers"] > 0
    # The selftest paper passes the number gate, so every stated number traces to the registry.
    assert stats["numbers_matched"] == stats["numbers"]
    assert claims["sources"]["sections"] == "package/paper_source/sections"
    assert claims["skipped_sections"] == ["ai_statement", "reproducibility"]
    history = revision_history(run_dir)
    assert [r["round"] for r in history["rounds"]][:2] == [0, 1]
    assert history["rounds"][1]["findings"] and history["text_source"] == "review_builds"
    graph = lineage_graph(run_dir)
    assert "numbers@v1" in upstream(graph, "draft@v1")
