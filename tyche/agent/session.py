"""An agent session: a model working through tools until its task is done.

The loop follows the shape of coding agents such as Claude Code and Codex, with Tyche's
evidence boundary kept in host code:

* the model acts only through tools, whose results come back as the next message;
* permissions decide which tools a session may see and call (``policy``);
* hooks run host checks around tools and when the model tries to stop, so work is
  verified before a session ends (a failed stop check hands the task back);
* a todo list keeps multi-step work planned and visible;
* subagents run focused tasks in a fresh context and return only their answer;
* a long history is compacted into a summary instead of being cut off;
* every turn, call, and result is written to a transcript.

A session is one append-only conversation (see :class:`tyche.llm.Conversation`), so the
provider's prefix cache serves every earlier turn. Later tasks extend the same
conversation, and a rejected task is undone by truncating it back to a checkpoint.
"""

from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from tyche.agent.policy import PermissionPolicy
from tyche.agent.todos import Todo, TodoList
from tyche.agent.tools import (
    PROTOCOL,
    ProtocolError,
    Tool,
    ToolCall,
    ToolResult,
    bind_args,
    parse_calls,
    render_manual,
    render_results,
)
from tyche.llm import Conversation, LLMClient
from tyche.textutil import count_tokens, truncate_tokens

# Hook signatures. A hook may be sync or async.
BeforeTool = Callable[["AgentSession", ToolCall, Tool], "str | None | Awaitable[str | None]"]
AfterTool = Callable[["AgentSession", ToolCall, Tool, ToolResult], "str | None | Awaitable[str | None]"]
OnStop = Callable[["AgentSession"], "str | None | Awaitable[str | None]"]

COMPACT_INSTRUCTION = (
    "Your conversation is about to be compacted to save context. Write a summary that lets you continue "
    "without it: the task, what you have done so far and why, decisions and their reasons, what the latest "
    "tool results showed, open problems, and your next steps. Be specific (section names, finding ids, "
    "exact error messages); do not restate large texts that tools can show you again. Do not call tools; "
    "reply with the summary only."
)


@dataclass
class Hooks:
    before_tool: list[BeforeTool] = field(default_factory=list)
    after_tool: list[AfterTool] = field(default_factory=list)
    on_stop: list[OnStop] = field(default_factory=list)


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


@dataclass
class Outcome:
    status: str  # done | blocked | max_turns
    final_text: str = ""
    result: Any = None
    turns: int = 0
    tool_calls: int = 0
    open_issue: str = ""


@dataclass
class SessionState:
    """What :meth:`AgentSession.checkpoint` saves and :meth:`AgentSession.rollback` restores."""

    conversation: Conversation
    mark: int
    pending: str
    todos: list[Todo]
    compactions: int


class AgentSession:
    def __init__(
        self,
        llm: LLMClient,
        *,
        name: str,
        instructions: str,
        tools: list[Tool],
        policy: PermissionPolicy | None = None,
        context: str = "",
        hooks: Hooks | None = None,
        todos: TodoList | None = None,
        purpose: str | None = None,
        max_turns: int = 30,
        max_stop_blocks: int = 3,
        compact_at_tokens: int = 100_000,
        state_fn: Callable[[], str] | None = None,
        transcript: Path | None = None,
        log: Callable[..., None] | None = None,
    ):
        self.llm = llm
        self.name = name
        self.policy = policy or PermissionPolicy()
        self.hooks = hooks or Hooks()
        self.todos = todos
        self.purpose = purpose or f"agent:{name}"
        self.max_turns = max_turns
        self.max_stop_blocks = max_stop_blocks
        self.compact_at_tokens = compact_at_tokens
        self.state_fn = state_fn
        self.transcript = transcript
        self.log = log or (lambda *a, **k: None)
        all_tools = list(tools) + ([todos.tool()] if todos is not None else [])
        names = [t.name for t in all_tools]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate tool names in session {name}: {names}")
        self.tools = {t.name: t for t in self.policy.visible(all_tools)}
        # Stable for the whole session: instructions, protocol, tool manual, then shared context.
        self.system = (
            instructions.strip()
            + "\n\n"
            + PROTOCOL
            + "\n\n<tools>\n"
            + render_manual(list(self.tools.values()))
            + "\n</tools>"
            + ("\n\n" + context.strip() if context.strip() else "")
        )
        self.conversation = Conversation(self.system)
        # Results of a batch that ended the previous task; sent first with the next task.
        self._pending = ""
        self.task = ""
        self.compactions = 0
        self.turns_total = 0
        self.calls_total = 0

    # -- state -----------------------------------------------------------
    def checkpoint(self) -> SessionState:
        return SessionState(
            self.conversation,
            self.conversation.checkpoint(),
            self._pending,
            self.todos.snapshot() if self.todos else [],
            self.compactions,
        )

    def rollback(self, state: SessionState) -> None:
        """Undo everything since ``state``: truncate, never edit, so the rest stays a cached prefix."""
        state.conversation.rollback(state.mark)
        self.conversation = state.conversation
        self._pending = state.pending
        self.compactions = state.compactions
        if self.todos is not None:
            self.todos.set(state.todos)

    def export_state(self) -> dict[str, Any]:
        return {
            "system": self.conversation.system,
            "turns": list(self.conversation.turns),
            "pending": self._pending,
            "todos": self.todos.to_list() if self.todos else [],
            "compactions": self.compactions,
        }

    def import_state(self, state: dict[str, Any] | None) -> bool:
        """Resume a saved session if it was built with the same instructions, tools, and context."""
        if not state or state.get("system") != self.system:
            return False
        self.conversation.turns = [dict(t) for t in state.get("turns") or []]
        self._pending = str(state.get("pending") or "")
        self.compactions = int(state.get("compactions") or 0)
        if self.todos is not None:
            self.todos.set([Todo(**t) for t in state.get("todos") or []])
        return True

    # -- transcript --------------------------------------------------------
    def _record(self, kind: str, **fields: Any) -> None:
        if self.transcript is None:
            return
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": round(time.time(), 3), "session": self.name, "kind": kind, **fields}
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    # -- the loop ------------------------------------------------------------
    def _reminder(self, turns_left: int) -> str:
        parts = []
        if self.todos is not None and self.todos.items:
            parts.append("<todos>\n" + self.todos.render() + "\n</todos>")
        if turns_left <= 3:
            parts.append(f"<budget>{turns_left} turn(s) left for this task; finish the most important work first.</budget>")
        return "\n".join(parts)

    async def _execute(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.tool)
        if tool is None:
            return ToolResult(f"unknown tool {call.tool!r}; available: {', '.join(self.tools)}", ok=False)
        refusal = await self.policy.check(call, tool)
        if refusal:
            return ToolResult(refusal, ok=False)
        for hook in self.hooks.before_tool:
            reason = await _maybe(hook(self, call, tool))
            if reason:
                return ToolResult(f"blocked by the host: {reason}", ok=False)
        try:
            args = bind_args(tool, call.raw_args)
        except ValueError as exc:
            return ToolResult(str(exc), ok=False)
        try:
            result = await tool.invoke(args)
        except Exception as exc:  # noqa: BLE001 - a failing tool is reported to the agent, which can adapt
            result = ToolResult(f"{type(exc).__name__}: {exc}"[:2000], ok=False)
        notes = []
        for hook in self.hooks.after_tool:
            note = await _maybe(hook(self, call, tool, result))
            if note:
                notes.append(note)
        if notes:
            result = ToolResult(result.text.rstrip() + "\n" + "\n".join(notes), result.ok, result.data)
        return result

    async def _compact(self, upcoming: str) -> str:
        """Summarise the conversation and start a new one; returns the first message of the new one."""
        reply = await self.llm.complete(
            system=self.conversation.system,
            user=(upcoming + "\n\n" if upcoming else "") + COMPACT_INSTRUCTION,
            purpose=f"{self.purpose}:compact",
            history=list(self.conversation.turns),
            continues=True,
        )
        before = self.conversation.tokens()
        self.conversation = Conversation(self.system)
        self.compactions += 1
        self._record("compact", tokens_before=before, summary=reply.text)
        self.log("agent.compact", session=self.name, tokens_before=before)
        parts = [
            "This conversation was compacted. Your summary of the work so far:",
            "<session_summary>\n" + reply.text.strip() + "\n</session_summary>",
        ]
        if self.state_fn is not None:
            parts.append("<current_state>\n" + self.state_fn() + "\n</current_state>")
        parts.append("<task>\n" + self.task + "\n</task>")
        if upcoming:
            parts.append("The latest results, sent before the summary:\n" + truncate_tokens(upcoming, 6000))
        parts.append("Continue the task.")
        return "\n\n".join(parts)

    async def run(self, task: str, *, max_turns: int | None = None) -> Outcome:
        """Work on ``task`` in this session's conversation until done or out of turns."""
        self.task = task
        limit = max_turns or self.max_turns
        message = (self._pending + "\n\n" if self._pending else "") + task
        self._pending = ""
        reminder = self._reminder(limit)
        if reminder:
            message += "\n\n" + reminder
        self._record("task", text=task)
        self.log("agent.task", session=self.name, turns=limit)
        stop_blocks = 0
        calls_made = 0
        for turn in range(1, limit + 1):
            if self.conversation.tokens() + count_tokens(message) > self.compact_at_tokens and self.conversation.turns:
                message = await self._compact(message)
            reply = await self.conversation.ask(self.llm, message, purpose=f"{self.purpose}:turn")
            self.turns_total += 1
            try:
                calls = parse_calls(reply.text)
            except ProtocolError as exc:
                self._record("assistant", turn=turn, text=reply.text, error=str(exc))
                message = f"<protocol_error>{exc}</protocol_error>\nNo tool ran. Fix the call format and try again."
                continue
            self._record("assistant", turn=turn, text=reply.text, calls=[c.tool for c in calls])
            if not calls:
                reasons = [r for r in [await _maybe(h(self)) for h in self.hooks.on_stop] if r]
                if not reasons:
                    self.log("agent.done", session=self.name, turns=turn, calls=calls_made)
                    return Outcome("done", reply.text, None, turn, calls_made)
                reason = "\n".join(reasons)
                self._record("stop_blocked", turn=turn, reason=reason)
                self.log("agent.stop_blocked", session=self.name, turn=turn)
                if stop_blocks >= self.max_stop_blocks:
                    return Outcome("blocked", reply.text, None, turn, calls_made, reason)
                stop_blocks += 1
                message = (
                    "<host_checks>\nThe task is not finished. The host's checks found:\n"
                    + reason
                    + "\n</host_checks>\nFix these, then reply without a tool call when done."
                )
                continue
            results: list[tuple[ToolCall, ToolResult]] = []
            for call in calls:
                result = await self._execute(call)
                results.append((call, result))
                calls_made += 1
                self.calls_total += 1
                self._record("result", turn=turn, tool=call.tool, ok=result.ok, text=result.text)
                self.log("agent.tool", session=self.name, tool=call.tool, ok=result.ok)
                tool = self.tools.get(call.tool)
                if result.ok and tool is not None and tool.ends_session:
                    self._pending = render_results(results)
                    self.log("agent.done", session=self.name, turns=turn, calls=calls_made)
                    return Outcome("done", reply.text, result.data, turn, calls_made)
            message = render_results(results)
            reminder = self._reminder(limit - turn)
            if reminder:
                message += "\n\n" + reminder
        self._pending = message
        self.log("agent.max_turns", session=self.name, turns=limit, calls=calls_made)
        return Outcome("max_turns", "", None, limit, calls_made)


@dataclass
class Subagent:
    """A named helper the lead agent can delegate a focused task to.

    ``build`` returns a fresh session each time, so the helper starts from a clean context
    and only its final answer reaches the lead agent.
    """

    name: str
    description: str
    build: Callable[[], AgentSession]
    max_answer_tokens: int = 2500


def delegate_tool(subagents: list[Subagent], *, log: Callable[..., None] | None = None) -> Tool:
    from pydantic import BaseModel, Field

    by_name = {s.name: s for s in subagents}

    class DelegateArgs(BaseModel):
        agent: str = Field(description="One of: " + ", ".join(by_name))
        task: str = Field(description="A self-contained task: the helper sees nothing of this conversation.")

    async def run(args: DelegateArgs) -> ToolResult:
        helper = by_name.get(args.agent)
        if helper is None:
            return ToolResult(f"no helper named {args.agent!r}; choose one of {', '.join(by_name)}", ok=False)
        session = helper.build()
        (log or (lambda *a, **k: None))("agent.delegate", helper=helper.name)
        outcome = await session.run(args.task)
        answer = outcome.final_text.strip() or "(the helper returned no answer)"
        if outcome.status != "done":
            answer += f"\n(helper stopped: {outcome.status})"
        return ToolResult(truncate_tokens(answer, helper.max_answer_tokens))

    manual = "\n".join(f"- {s.name}: {s.description}" for s in subagents)
    return Tool(
        "delegate",
        "Hand a focused task to a helper agent that works in a fresh context with read-only tools and "
        "returns only its answer. Helpers:\n" + manual,
        run,
        DelegateArgs,
        effect="delegate",
    )
