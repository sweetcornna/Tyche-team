"""Revision history of the review loop: what each round changed, and which findings it answered.

Where the text of each round lives (see ``RevisionLoop`` and ``stage_review``):

* the review stage saves only the draft it started from (its input) and the
  best accepted text (``paper``), next to ``ledger`` and ``review_rounds``;
* each round's candidate is built in ``review/build_r<N>/sections/*.tex``;
  the build directory keeps the round's final text (after compile repairs and
  page trims), including a rejected candidate;
* round 0 reviews the draft; an accepted round replaces the current text, a
  rejected one is reverted, so the paper equals the last accepted round.

Build directories are not artifacts, so they are used only when they provably
belong to the saved review: ``review/rounds.json`` must equal the
``review_rounds`` artifact and the last accepted build must equal ``paper``.
Otherwise the history falls back to the artifacts, which determine the text of
a round only when a single revision round was accepted after a clean round-0
build.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from tyche.textutil import word_count
from tyche.trace.claims import GENERATED_SECTIONS, section_sort_key
from tyche.trace.lineage import latest_record, load_json, read_provenance

_FINDING_FIELDS = ("id", "source", "severity", "dimension", "section", "problem", "fix", "status", "response")


def _json_sections(run_dir: Path, record: dict[str, Any] | None) -> dict[str, str]:
    data = load_json(run_dir / str(record["path"])) if record else None
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, dict):
        return {}
    return {str(name): str(text or "").strip() for name, text in sections.items()}


def _build_sections(run_dir: Path, row: dict[str, Any], names: set[str]) -> dict[str, str] | None:
    """The writer sections a round built, or None if its build directory is gone."""
    recorded = str((row.get("build") or {}).get("build_dir") or "")
    directory = run_dir / "review" / (Path(recorded).name if recorded else f"build_r{row.get('round')}") / "sections"
    if not directory.is_dir():
        return None
    out = {}
    for file in sorted(directory.glob("*.tex")):
        name = file.stem
        wanted = name in names if names else not (name in GENERATED_SECTIONS or name.endswith("_floats"))
        if wanted:
            try:
                out[name] = file.read_text(encoding="utf-8").strip()
            except OSError:
                return None
    return out


def _section_diffs(before: dict[str, str], after: dict[str, str], labels: tuple[str, str]) -> list[dict[str, Any]]:
    out = []
    for name in sorted(set(before) | set(after), key=section_sort_key):
        old, new = before.get(name, ""), after.get(name, "")
        if old == new:
            continue
        diff = difflib.unified_diff(
            old.splitlines(), new.splitlines(), fromfile=f"{name} ({labels[0]})", tofile=f"{name} ({labels[1]})",
            n=3, lineterm="",
        )
        out.append({"name": name, "before_words": word_count(old), "after_words": word_count(new), "diff": "\n".join(diff)})
    return out


def _finding(entry_id: str, ledger: dict[str, dict[str, Any]], round_no: int) -> dict[str, Any]:
    entry = ledger.get(entry_id)
    if entry is None:
        return {**dict.fromkeys(_FINDING_FIELDS), "id": entry_id, "round_history": [], "in_ledger": False}
    row = {name: entry.get(name) for name in _FINDING_FIELDS}
    row["round_history"] = [str(h) for h in entry.get("history") or [] if str(h).startswith(f"r{round_no}:")]
    row["in_ledger"] = True
    return row


def revision_history(run_dir: Path) -> dict[str, Any]:
    """Per review round: section diffs, word counts, the findings it addressed, and its score."""
    run_dir = Path(run_dir)
    rows = read_provenance(run_dir)
    out: dict[str, Any] = {
        "rounds": [], "review_rounds": None, "draft": None, "paper": None, "ledger": None, "text_source": None,
        "overall": [],
    }
    rounds_rec = latest_record(rows, "review_rounds")
    rounds = load_json(run_dir / str(rounds_rec["path"])) if rounds_rec else None
    if not isinstance(rounds, list):
        return out
    rounds = sorted((r for r in rounds if isinstance(r, dict) and "round" in r), key=lambda r: int(r["round"]))
    # The paper and ledger saved by the same review run precede its review_rounds record.
    earlier = rows[: next(i for i, row in enumerate(rows) if row is rounds_rec)]
    draft_id = next((str(i) for i in rounds_rec.get("inputs") or [] if str(i).startswith("draft@")), None)
    draft_rec = next((row for row in rows if row["id"] == draft_id), None) or latest_record(earlier, "draft")
    paper_rec = latest_record(earlier, "paper") or latest_record(rows, "paper")
    ledger_rec = latest_record(earlier, "ledger") or latest_record(rows, "ledger")
    draft = _json_sections(run_dir, draft_rec)
    paper = _json_sections(run_dir, paper_rec)
    ledger_data = load_json(run_dir / str(ledger_rec["path"])) if ledger_rec else None
    ledger = {
        str(e.get("id")): e
        for e in (ledger_data.get("entries") or [] if isinstance(ledger_data, dict) else [])
        if isinstance(e, dict)
    }
    out.update(
        review_rounds=rounds_rec["id"],
        draft=draft_rec["id"] if draft_rec else None,
        paper=paper_rec["id"] if paper_rec else None,
        ledger=ledger_rec["id"] if ledger_rec else None,
    )
    if draft and paper:
        out["overall"] = _section_diffs(draft, paper, (str(draft_rec["id"]), str(paper_rec["id"])))

    names = set(draft) | set(paper)
    builds = {int(r["round"]): _build_sections(run_dir, r, names) for r in rounds}
    accepted_rounds = [int(r["round"]) for r in rounds if r.get("accepted")]
    trusted = load_json(run_dir / "review" / "rounds.json") == load_json(run_dir / str(rounds_rec["path"]))
    if trusted and paper and accepted_rounds:
        trusted = builds.get(max(accepted_rounds)) == paper
    if not trusted:
        builds = {}
    out["text_source"] = "review_builds" if trusted and any(v is not None for v in builds.values()) else "artifacts"

    first = rounds[0] if rounds else {}
    clean_start = int(first.get("round", -1)) == 0 and not any(
        (first.get("build") or {}).get(key) for key in ("repairs", "trims")
    )
    revisions_accepted = [n for n in accepted_rounds if n > 0]
    current: dict[str, str] | None = draft or None
    for row in rounds:
        n = int(row["round"])
        accepted = bool(row.get("accepted"))
        after = builds.get(n)
        source = "review_build" if after is not None else None
        before = current
        if n == 0:
            before = draft or None
            if after is None and before is not None and clean_start:
                after, source = before, "artifacts"
        elif after is None and accepted and revisions_accepted == [n] and clean_start and draft and paper:
            after, source = paper, "artifacts"
        if before is None:
            sections, note = [], "text before this round not retained"
        elif after is None:
            sections, note = [], ("revised text not retained" if accepted else "candidate not retained")
        else:
            sections = _section_diffs(before, after, ("before" if n else str(out["draft"]), f"round {n}"))
            if n == 0:
                note = "review of the written draft" + ("; compile repairs or page trims changed it" if sections else "")
            else:
                note = None if accepted else "candidate rejected; the paper kept the previous text"
        if accepted:
            current = after
        out["rounds"].append(
            {
                "round": n,
                "accepted": accepted,
                "composite": row.get("composite"),
                "delta": row.get("delta"),
                "blockers": row.get("blockers"),
                "sections_revised": list(row.get("sections_revised") or []),
                "sections": sections,
                "findings": [_finding(str(i), ledger, n) for i in row.get("findings_addressed") or []],
                "text_source": source,
                "note": note,
            }
        )
    return out
