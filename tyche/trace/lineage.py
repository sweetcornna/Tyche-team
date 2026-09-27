"""Artifact lineage: which artifact versions each version was derived from.

Built from ``provenance.jsonl``, where the workspace records every artifact
version with its producing stage, its declared inputs, and the previous
version of the same name. Reading is tolerant: a run that is still writing
may leave a partial last line, which is skipped rather than raising.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from tyche import STAGES


def read_provenance(run_dir: Path) -> list[dict[str, Any]]:
    """Provenance rows of a run in write order; unreadable lines are skipped."""
    path = Path(run_dir) / "provenance.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id") and row.get("name"):
            rows.append(row)
    return rows


def load_json(path: Path) -> Any:
    """Parsed JSON of ``path``, or None if it is missing or not (yet) valid JSON."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest_record(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """The highest version of ``name``, as ``Workspace.latest`` picks it."""
    found = [row for row in rows if row.get("name") == name]
    return max(found, key=lambda row: int(row.get("version") or 0)) if found else None


def _relative(path: str, run_dir: Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(run_dir).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def lineage_graph(run_dir: Path) -> dict[str, Any]:
    """Nodes (artifact versions), input/parent edges, and the stages that produced them."""
    run_dir = Path(run_dir)
    rows = read_provenance(run_dir)
    latest_version: dict[str, int] = {}
    for row in rows:
        latest_version[row["name"]] = max(latest_version.get(row["name"], 0), int(row.get("version") or 0))
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        version = int(row.get("version") or 0)
        nodes.append(
            {
                "id": row["id"],
                "name": row["name"],
                "version": version,
                "stage": row.get("stage"),
                "sha256": row.get("sha256"),
                "path": _relative(str(row.get("path") or ""), run_dir),
                "latest": version == latest_version[row["name"]],
            }
        )
        for source in row.get("inputs") or []:
            edges.append({"from": str(source), "to": row["id"], "kind": "input"})
        if row.get("parent"):
            edges.append({"from": str(row["parent"]), "to": row["id"], "kind": "parent"})
    present = [node["stage"] for node in nodes if node["stage"]]
    stages = [stage for stage in STAGES if stage in present]
    stages += [stage for stage in dict.fromkeys(present) if stage not in STAGES]
    missing = sorted({edge["from"] for edge in edges} - seen)
    return {"nodes": nodes, "edges": edges, "stages": stages, "missing": missing}


def upstream(graph: dict[str, Any], artifact_id: str) -> list[str]:
    """Every artifact ``artifact_id`` transitively derives from (inputs and parents), nearest first."""
    sources: dict[str, list[str]] = {}
    for edge in graph.get("edges", []):
        sources.setdefault(edge["to"], []).append(edge["from"])
    out: list[str] = []
    seen = {artifact_id}
    queue = deque([artifact_id])
    while queue:
        for source in sources.get(queue.popleft(), []):
            if source not in seen:
                seen.add(source)
                out.append(source)
                queue.append(source)
    return out
