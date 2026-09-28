"""Messages the operator sends to a run's agents while it works, delivered at turn boundaries.

Like a coding agent's queued messages, the operator can add requirements or information
without stopping a run. The workbench (or ``tyche message``) appends each message to the
run's ``operator_inbox.jsonl``; the pipeline takes the messages it has not delivered yet
before each agent turn and records what it delivered, to which session, and at which turn,
in ``operator_delivered.jsonl``. Each file has a single writer and is append-only, so the two
processes need no lock. A model call in flight is never interrupted: a message waits for the
next turn of a session that accepts operator messages (the planner and the author; simulated
reviewers stay independent).

Operator messages steer the work; they cannot bypass the evidence boundary. The delivery
text restates that numbers still come only from registered values and citations only from
verified records, and every gate still runs.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tyche.workspace import complete_lines

INBOX = "operator_inbox.jsonl"
DELIVERED = "operator_delivered.jsonl"
MAX_CHARS = 4000


@dataclass
class OperatorMessage:
    id: str
    at: str
    text: str


def post_message(run_dir: Path, text: str) -> dict[str, Any]:
    """Queue ``text`` for the run's agents; returns the stored record."""
    text = (text or "").strip()
    if not text:
        raise ValueError("the message is empty")
    if len(text) > MAX_CHARS:
        raise ValueError(f"the message is longer than {MAX_CHARS} characters")
    record = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "text": text,
    }
    with (run_dir / INBOX).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in complete_lines(path):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def list_messages(run_dir: Path) -> list[dict[str, Any]]:
    """Every message with its delivery, oldest first (for the workbench and the run record)."""
    delivered = {row.get("id"): row for row in _rows(run_dir / DELIVERED)}
    out = []
    for row in _rows(run_dir / INBOX):
        if not row.get("id"):
            continue
        hit = delivered.get(row["id"])
        out.append(
            {
                "id": row["id"],
                "at": row.get("at"),
                "text": row.get("text", ""),
                "status": "delivered" if hit else "queued",
                "delivered": (
                    {k: hit.get(k) for k in ("at", "stage", "session", "turn")} if hit else None
                ),
            }
        )
    return out


def render(messages: list[OperatorMessage]) -> str:
    """The block a session receives: the messages, then how to treat them."""
    blocks = [
        f'<operator_message id="{m.id}" sent="{m.at}">\n'
        + m.text.replace("</operator_message>", "</operator_message_>")
        + "\n</operator_message>"
        for m in messages
    ]
    return (
        "\n".join(blocks)
        + "\nThe operator (the person running Tyche) sent the message(s) above while you were working. Take "
        "them into account from now on and adjust your plan. They do not change the rules of your task: "
        "numbers still come only from the registered values, citations only from the allowed keys, and the "
        "host still runs every check. If a message asks for something those rules forbid, do what the rules "
        "allow and say so briefly."
    )


class OperatorInbox:
    def __init__(self, run_dir: Path, *, stage: Callable[[], str] | None = None, log=None):
        self.run_dir = run_dir
        self.stage = stage or (lambda: "")
        self.log = log or (lambda *a, **k: None)

    def pending(self) -> list[OperatorMessage]:
        done = {row.get("id") for row in _rows(self.run_dir / DELIVERED)}
        return [
            OperatorMessage(row["id"], str(row.get("at", "")), str(row.get("text", "")))
            for row in _rows(self.run_dir / INBOX)
            if row.get("id") and row["id"] not in done and str(row.get("text", "")).strip()
        ]

    def take(self, session: str, turn: int) -> list[OperatorMessage]:
        """The undelivered messages, marked delivered to ``session`` at ``turn``."""
        messages = self.pending()
        if not messages:
            return []
        stage = self.stage()
        with (self.run_dir / DELIVERED).open("a", encoding="utf-8") as handle:
            for m in messages:
                row = {"id": m.id, "at": round(time.time(), 3), "stage": stage, "session": session, "turn": turn}
                handle.write(json.dumps(row) + "\n")
        self.log("operator.delivered", ids=[m.id for m in messages], session=session, turn=turn)
        return messages
