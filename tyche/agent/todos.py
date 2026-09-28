"""The agent's working plan: a short todo list it keeps up to date.

The agent replaces the whole list with ``update_todos`` as it works, marking at most one
item in progress. The host shows the list to the operator, restates it after every tool
batch and after compaction, and may seed it (one item per section to write, or per review
finding to address). The list is a plan, not a gate: stop checks look at the paper itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from tyche.agent.tools import Tool, ToolResult

Status = Literal["pending", "in_progress", "completed", "cancelled"]
_MARK = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "cancelled": "[-]"}


@dataclass
class Todo:
    id: str
    content: str
    status: str = "pending"


class TodoItem(BaseModel):
    id: str = Field(default="", description="Short stable id, e.g. 'method' or 'F3'; numbered if omitted.")
    content: str = Field(
        description="What to do, as one imperative sentence.",
        validation_alias=AliasChoices("content", "text", "title", "task"),
    )
    status: Status = "pending"


class TodoArgs(BaseModel):
    todos: list[TodoItem] = Field(description="The complete updated list; it replaces the previous one.")


class TodoList:
    def __init__(self, items: list[Todo] | None = None, *, on_change=None):
        self.items: list[Todo] = list(items or [])
        self.on_change = on_change

    def set(self, items: list[Todo]) -> None:
        self.items = list(items)
        if self.on_change is not None:
            self.on_change(self)

    def open(self) -> list[Todo]:
        return [t for t in self.items if t.status in ("pending", "in_progress")]

    def render(self) -> str:
        if not self.items:
            return "(empty)"
        return "\n".join(f"{_MARK.get(t.status, '[ ]')} {t.id}: {t.content}" for t in self.items)

    def to_list(self) -> list[dict[str, str]]:
        return [asdict(t) for t in self.items]

    def snapshot(self) -> list[Todo]:
        return [Todo(t.id, t.content, t.status) for t in self.items]

    def update(self, args: TodoArgs) -> ToolResult:
        for i, item in enumerate(args.todos, 1):
            item.id = item.id or str(i)
        ids = [t.id for t in args.todos]
        if len(set(ids)) != len(ids):
            return ToolResult("todo ids must be unique", ok=False)
        active = [t.id for t in args.todos if t.status == "in_progress"]
        if len(active) > 1:
            return ToolResult(f"only one item may be in progress at a time, got {', '.join(active)}", ok=False)
        self.set([Todo(t.id, t.content, t.status) for t in args.todos])
        return ToolResult("todo list updated:\n" + self.render())

    def tool(self) -> Tool:
        return Tool(
            "update_todos",
            "Replace your todo list. Use it to plan multi-step work, mark the item you start as in_progress "
            "(one at a time), and mark items completed as soon as they are done. Cancel items that no longer apply.",
            self.update,
            TodoArgs,
            effect="read",
        )
