"""Permission modes for agent tools.

A mode names the effects its sessions may use; per-tool lists override it. Tools a session
may not use are left out of its manual, and a call to one is refused with the reason, so
the agent can adapt instead of failing. Tools that need an operator's approval ask an
approver; without one they are refused.

The evidence boundary is not a permission: no tool lets a model register a number, add a
bibliography entry, or mark a gate as passed, whatever the mode.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from tyche.agent.tools import Tool, ToolCall

MODES: dict[str, frozenset[str]] = {
    # Look and check only, e.g. reviewers and the planner's exploration.
    "read_only": frozenset({"read", "check", "result", "delegate"}),
    # Edit the paper in the run's workspace; no network.
    "workspace_write": frozenset({"read", "check", "edit", "result", "delegate"}),
    # Everything, including scholarly API searches.
    "full": frozenset({"read", "check", "edit", "external", "result", "delegate"}),
}

Decision = Literal["allow", "ask", "deny"]
Approver = Callable[[ToolCall, Tool], "bool | Awaitable[bool]"]


@dataclass
class PermissionPolicy:
    mode: str = "workspace_write"
    allow: set[str] = field(default_factory=set)
    deny: set[str] = field(default_factory=set)
    ask: set[str] = field(default_factory=set)
    approver: Approver | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown permission mode {self.mode!r}; choose one of {', '.join(MODES)}")

    def decide(self, tool: Tool) -> Decision:
        if tool.name in self.deny:
            return "deny"
        if tool.name in self.ask:
            return "ask"
        if tool.name in self.allow or tool.effect in MODES[self.mode]:
            return "allow"
        return "deny"

    def visible(self, tools: list[Tool]) -> list[Tool]:
        return [t for t in tools if self.decide(t) != "deny"]

    async def check(self, call: ToolCall, tool: Tool) -> str | None:
        """None if the call may run, else why not."""
        decision = self.decide(tool)
        if decision == "allow":
            return None
        if decision == "deny":
            return f"permission denied: {tool.name} ({tool.effect}) is not allowed in {self.mode} mode"
        if self.approver is None:
            return f"permission denied: {tool.name} needs an operator's approval and none is available"
        approved = self.approver(call, tool)
        if inspect.isawaitable(approved):
            approved = await approved
        return None if approved else f"the operator declined {tool.name}"

    def narrowed(self, mode: str) -> "PermissionPolicy":
        """A policy for a subagent: the stricter of this mode and ``mode``, same lists."""
        allowed = MODES[self.mode] & MODES[mode]
        stricter = next(name for name, effects in MODES.items() if effects == allowed) if allowed in MODES.values() else mode
        return PermissionPolicy(stricter, set(self.allow), set(self.deny), set(self.ask), self.approver)

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode, "allow": sorted(self.allow), "deny": sorted(self.deny), "ask": sorted(self.ask)}
