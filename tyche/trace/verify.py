"""Offline verification of a delivered paper package (``tyche verify``).

Every check reruns deterministic code on the package's own run record; nothing calls a
model or the network. A reproduction auditor can therefore confirm, from the package
alone, that

* every recorded artifact version still has the bytes its provenance row hashed;
* the paper PDF is the one the package recorded;
* the statistics and the allowed-numbers registry recompute exactly from the packaged
  experiment metrics, plan, design, and evidence;
* every number in the gated sections of the paper source matches that registry;
* every citation resolves to a bibliography entry that came from a verified record;
* the shipped claim-evidence map is what the claim-map code produces for this paper.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tyche.workspace import read_jsonl, sha256_file, sha256_tree

_BIB_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def locate_package(path: Path) -> Path:
    """The package directory for a package path or a run directory that contains one."""
    path = Path(path).expanduser().resolve()
    for candidate in (path, path / "package"):
        if (candidate / "run_record").is_dir():
            return candidate
    raise FileNotFoundError(f"{path} is neither a Tyche package nor a run directory with a package/")


def _rows_before(rows: list[dict[str, Any]], stop_id: str) -> list[dict[str, Any]]:
    """Provenance rows written before the row ``stop_id`` (the inputs available when it was made)."""
    out = []
    for row in rows:
        if row.get("id") == stop_id:
            return out
        out.append(row)
    return out


def _latest(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    found = [r for r in rows if r.get("name") == name]
    return max(found, key=lambda r: int(r.get("version", 0))) if found else None


def _check_provenance(record: Path, rows: list[dict[str, Any]]) -> Check:
    drifted = []
    for row in rows:
        target = record / str(row.get("path", ""))
        if not target.exists():
            drifted.append(f"{row.get('id')} (missing)")
            continue
        actual = sha256_tree(target) if row.get("kind") == "tree" else sha256_file(target)
        if actual != row.get("sha256"):
            drifted.append(str(row.get("id")))
    if drifted:
        return Check("provenance", False, f"{len(drifted)} of {len(rows)} artifact versions changed: {', '.join(drifted[:8])}")
    return Check("provenance", True, f"{len(rows)} artifact versions match their recorded SHA-256")


def _check_pdf(package: Path) -> Check:
    meta = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
    for name in ("paper.pdf", "paper_UNVERIFIED.pdf"):
        pdf = package / name
        if pdf.exists():
            if sha256_file(pdf) != meta.get("paper_pdf_sha256"):
                return Check("paper", False, f"{name} differs from the PDF recorded at packaging")
            note = " (packaged with --allow-gate-failures: UNVERIFIED)" if name != "paper.pdf" else ""
            return Check("paper", True, f"{name} is the PDF recorded at packaging{note}")
    return Check("paper", False, "no paper.pdf in the package")


def _analysis_settings(record: Path) -> dict[str, Any]:
    """The run's analysis settings: its saved config, else the packaged defaults; the seed the
    analysis stage recorded takes precedence."""
    config_path = record / "config.json"
    if config_path.exists():
        settings = dict(json.loads(config_path.read_text(encoding="utf-8")).get("analysis") or {})
    else:
        from tyche.config import TycheConfig

        settings = dict(TycheConfig.load(None).get("analysis") or {})
    state = json.loads((record / "state.json").read_text(encoding="utf-8")) if (record / "state.json").exists() else {}
    seed = (state.get("meta") or {}).get("analysis_seed")
    if seed is not None:
        settings["seed"] = seed
    return settings


def _recompute(record: Path, rows: list[dict[str, Any]]) -> tuple[Check, Check, Any]:
    """Recompute the analysis and the numbers registry from the rows the analysis stage read."""
    from tyche.analysis import analyze, build_registry
    from tyche.experiments import read_metrics_dir
    from tyche.planning import ResearchPlan, plan_markdown

    analysis_row, numbers_row = _latest(rows, "analysis"), _latest(rows, "numbers")
    if analysis_row is None or numbers_row is None:
        missing = Check("analysis", False, "the run record has no analysis artifact")
        return missing, Check("numbers", False, "the run record has no numbers artifact"), None
    earlier = _rows_before(rows, str(analysis_row["id"]))
    results_ids = [i for i in analysis_row.get("inputs", []) if str(i).startswith("experiment_results@")]
    results_row = next((r for r in rows if r.get("id") in results_ids), None) or _latest(earlier, "experiment_results")
    plan_row = _latest(earlier, "plan")
    if results_row is None or plan_row is None:
        missing = Check("analysis", False, "the experiment results or plan behind the analysis are missing")
        return missing, Check("numbers", False, "not recomputed"), None
    settings = _analysis_settings(record)
    plan = ResearchPlan.model_validate(json.loads((record / str(plan_row["path"])).read_text(encoding="utf-8")))
    analysis = analyze(
        read_metrics_dir(record / str(results_row["path"])),
        plan_metrics=plan.metrics,
        method_name=plan.method_name,
        resamples=int(settings.get("bootstrap_resamples", 2000)),
        permutations=int(settings.get("permutation_resamples", 5000)),
        confidence=float(settings.get("confidence", 0.95)),
        seed=int(settings.get("seed", 0)),
    )
    saved = json.loads((record / str(analysis_row["path"])).read_text(encoding="utf-8"))
    same = json.dumps(analysis.to_dict(), sort_keys=True) == json.dumps(saved, sort_keys=True)
    analysis_check = Check(
        "analysis",
        same,
        (f"statistics recompute exactly from {results_row['id']} ({len(analysis.comparisons)} paired comparisons)"
         if same else f"recomputed statistics differ from {analysis_row['id']}"),
    )
    design_row = _latest(earlier, "experiment_design")
    design = (record / str(design_row["path"])).read_text(encoding="utf-8") if design_row else plan_markdown(plan)
    manifest_row = _latest(earlier, "source_manifest")
    manifest = json.loads((record / str(manifest_row["path"])).read_text(encoding="utf-8")) if manifest_row else {}
    quotes = " ".join(card.get("quote", "") for card in manifest.get("evidence_cards", []))
    registry = build_registry(analysis, setup_texts={"design": design, "plan": plan_markdown(plan), "evidence_quotes": quotes})
    saved_numbers = json.loads((record / str(numbers_row["path"])).read_text(encoding="utf-8"))
    same_numbers = registry.to_list() == saved_numbers
    numbers_check = Check(
        "numbers",
        same_numbers,
        (f"the allowed-numbers registry ({len(saved_numbers)} values) recomputes exactly"
         if same_numbers else f"the recomputed registry differs from {numbers_row['id']}"),
    )
    return analysis_check, numbers_check, saved_numbers


def _paper_sections(package: Path) -> dict[str, str]:
    sections = package / "paper_source" / "sections"
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(sections.glob("*.tex"))} if sections.is_dir() else {}


def _check_paper_numbers(package: Path, numbers: list[dict[str, Any]] | None) -> Check:
    from tyche.analysis.registry import NumberRegistry
    from tyche.gates.checks import NUMBER_CHECKED_SECTIONS, check_numbers, numeric_tokens

    sections = _paper_sections(package)
    if not sections:
        return Check("paper numbers", False, "the package has no paper_source/sections")
    if numbers is None:
        return Check("paper numbers", False, "no registry to check against")
    findings = check_numbers(sections, NumberRegistry.from_list(numbers))
    checked = sum(len(numeric_tokens(sections.get(name, ""))) for name in NUMBER_CHECKED_SECTIONS)
    if findings:
        shown = "; ".join(f"{f.section}: {f.message}" for f in findings[:5])
        return Check("paper numbers", False, f"{len(findings)} of {checked} numbers match no computed value: {shown}")
    return Check("paper numbers", True, f"all {checked} numbers in {', '.join(NUMBER_CHECKED_SECTIONS)} match computed values")


def _check_citations(package: Path, record: Path, rows: list[dict[str, Any]]) -> Check:
    from tyche.paper.sanitize import cited_keys

    bib = package / "paper_source" / "refs.bib"
    bib_keys = set(_BIB_KEY.findall(bib.read_text(encoding="utf-8"))) if bib.exists() else set()
    cited: set[str] = set()
    for text in _paper_sections(package).values():
        cited.update(cited_keys(text))
    unknown = sorted(cited - bib_keys)
    manifest_row = _latest(rows, "source_manifest")
    manifest = json.loads((record / str(manifest_row["path"])).read_text(encoding="utf-8")) if manifest_row else {}
    verified = {str(p.get("key")) for p in manifest.get("papers", []) if isinstance(p, dict)}
    admitted = {str(e.get("key")) for e in read_jsonl(record / "events.jsonl") if e.get("kind") == "review.citation_admitted"}
    untraced = sorted(k for k in cited & bib_keys if k not in verified | admitted)
    if unknown or untraced:
        parts = []
        if unknown:
            parts.append(f"not in refs.bib: {', '.join(unknown[:8])}")
        if untraced:
            parts.append(f"not from a verified record: {', '.join(untraced[:8])}")
        return Check("citations", False, "; ".join(parts))
    return Check(
        "citations",
        True,
        f"{len(cited)} cited keys resolve to verified records ({len(cited & admitted)} admitted during review)",
    )


def _check_claims(package: Path, record: Path) -> Check:
    from tyche.trace.claims import claim_map_for_run

    shipped_path = package / "claims.json"
    if not shipped_path.exists():
        return Check("claims", False, "the package has no claims.json")
    shipped = json.loads(shipped_path.read_text(encoding="utf-8"))
    rebuilt = claim_map_for_run(record)
    if rebuilt is None:
        return Check("claims", False, "no paper text in the run record to rebuild the claim map from")

    def statuses(claims: dict[str, Any]) -> list[tuple[str, str]]:
        return [(c.get("sentence", ""), c.get("status", "")) for c in claims.get("claims", [])]

    same = shipped.get("stats") == rebuilt.get("stats") and statuses(shipped) == statuses(rebuilt)
    stats = rebuilt["stats"]
    detail = (
        f"{stats['claims']} claims ({stats['verified']} verified, {stats['weak']} weakly supported, "
        f"{stats['unverified']} unverified); {stats['numbers_matched']}/{stats['numbers']} numbers matched"
    )
    return Check("claims", same and stats["unverified"] == 0, detail if same else "the shipped claim map differs: " + detail)


def _built_with(package: Path) -> str:
    """The code the package was built with, for explaining a recomputation mismatch."""
    try:
        env = json.loads((package / "environment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    git = env.get("git") or {}
    commit = str(git.get("commit") or "")[:12]
    if not commit:
        return ""
    return f"; the package was built at commit {commit}{' with uncommitted changes' if git.get('dirty') else ''}"


def verify_package(path: Path) -> list[Check]:
    package = locate_package(path)
    record = package / "run_record"
    rows = [r for r in read_jsonl(record / "provenance.jsonl") if r.get("id") and r.get("name")]
    checks = [_check_provenance(record, rows), _check_pdf(package)]
    analysis_check, numbers_check, numbers = _recompute(record, rows)
    for check in (analysis_check, numbers_check):
        if not check.ok and "differ" in check.detail:
            check.detail += _built_with(package)
    checks += [analysis_check, numbers_check, _check_paper_numbers(package, numbers)]
    checks += [_check_citations(package, record, rows), _check_claims(package, record)]
    return checks


def report(checks: list[Check]) -> dict[str, Any]:
    return {"passed": all(c.ok for c in checks), "checks": [asdict(c) for c in checks]}
