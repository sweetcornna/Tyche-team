/**
 * Turn an agent session's transcript into an activity feed: what the agent said, groups of
 * consecutive look-ups, its edits and builds, plan updates, the operator's messages, and the
 * host's hand-backs. Pure functions, so the grouping and the one-line summaries are unit-tested.
 */
import type { AgentCall, AgentItem } from "../../api/types";

export type Todo = { id: string; content: string; status: string };

/** How a call is shown: looks (grouped), changes (their own row), plans, and results. */
export type CallKind =
  | "read"
  | "lookup"
  | "search"
  | "check"
  | "write"
  | "edit"
  | "title"
  | "build"
  | "respond"
  | "delegate"
  | "plan"
  | "submit"
  | "other";

const KINDS: Record<string, CallKind> = {
  read_section: "read",
  read_material: "read",
  paper_status: "check",
  lint: "check",
  check_plan: "check",
  lookup_numbers: "lookup",
  recall_lessons: "search",
  search_evidence: "search",
  search_literature: "search",
  write_section: "write",
  edit_section: "edit",
  set_title: "title",
  build_paper: "build",
  respond_to_finding: "respond",
  delegate: "delegate",
  update_todos: "plan",
  submit_plan: "submit",
  submit: "submit",
};

/** Kinds that only look at things; consecutive ones are folded into one group. */
export const LOOK_KINDS: ReadonlySet<CallKind> = new Set(["read", "lookup", "search", "check", "other"]);

export interface CallView {
  tool: string;
  kind: CallKind;
  /** What the call acted on: a section, a query, a helper's name. */
  target: string;
  /** One-line result summary (e.g. 414 words · no findings; 3 values). */
  outcome: OutcomePart[];
  /** null while the call has no result (not run, or still running). */
  ok: boolean | null;
  args: Record<string, string>;
  result: string;
  at?: number;
}

export type FeedBlock =
  | { type: "task"; text: string; at?: number }
  | { type: "say"; text: string; at?: number }
  | { type: "group"; calls: CallView[]; at?: number }
  | { type: "change"; call: CallView; at?: number }
  | { type: "plan"; todos: Todo[]; at?: number }
  | { type: "operator"; text: string; at?: number }
  | { type: "handback"; text: string; at?: number }
  | { type: "compact"; text: string; tokens: number; at?: number }
  | { type: "error"; text: string; at?: number };

export function kindOf(tool: string): CallKind {
  return KINDS[tool] ?? "other";
}

const firstLine = (text: string) => (text.split("\n").find((l) => l.trim()) ?? "").trim();

function clip(text: string, n = 72): string {
  return text.length > n ? text.slice(0, n - 1) + "…" : text;
}

/** One piece of a call's one-line result; the UI formats each in the reader's language. */
export type OutcomePart =
  | { k: "words"; n: number }
  | { k: "noFindings" }
  | { k: "findings"; blocker: number; major: number; minor: number }
  | { k: "notWritten" }
  | { k: "values"; n: number }
  | { k: "noMatch" }
  | { k: "results"; n: number }
  | { k: "noResults" }
  | { k: "pages"; n: number; of: number }
  | { k: "fixed" }
  | { k: "rebutted" }
  | { k: "text"; text: string };

/** Findings listed under a "checks …:" or "gate findings:" heading. */
function findings(text: string): OutcomePart | null {
  if (/\bno findings\b/.test(text)) return { k: "noFindings" };
  const rows = text.split("\n").filter((l) => /^- \[(blocker|major|minor)\]/.test(l));
  if (!rows.length) return null;
  const by = (s: string) => rows.filter((r) => r.startsWith(`- [${s}]`)).length;
  return { k: "findings", blocker: by("blocker"), major: by("major"), minor: by("minor") };
}

export function targetOf(call: AgentCall): string {
  const a = call.args;
  switch (call.tool) {
    case "read_section":
    case "write_section":
    case "edit_section":
    case "lint":
      return a.section ?? "";
    case "read_material":
      return a.name ?? "";
    case "lookup_numbers":
    case "search_evidence":
    case "search_literature":
    case "recall_lessons":
      return a.query ?? "";
    case "set_title":
      return a.title ?? "";
    case "respond_to_finding":
      return a.id ?? "";
    case "delegate":
      return a.agent ?? a.name ?? "";
    default: {
      const short = Object.values(a).find((v) => v.length <= 60 && !v.includes("\n"));
      return short ?? "";
    }
  }
}

/** The one-line result: words and findings for an edit, value counts for a look-up, errors' first line. */
export function outcomeOf(call: AgentCall): OutcomePart[] {
  const r = call.result;
  if (!r) return [];
  const text = r.text ?? "";
  const line = (n = 64): OutcomePart[] => {
    const first = firstLine(text);
    return first ? [{ k: "text", text: clip(first, n) }] : [];
  };
  if (!r.ok) return line();
  const count = (re: RegExp) => text.split("\n").filter((l) => re.test(l)).length;
  switch (call.tool) {
    case "write_section":
    case "edit_section": {
      const words = text.match(/: (\d+) words/);
      const f = findings(text);
      return [...(words ? [{ k: "words", n: Number(words[1]) } as OutcomePart] : []), ...(f ? [f] : [])];
    }
    case "read_section":
      if (/not written yet/.test(text)) return [{ k: "notWritten" }];
      return [{ k: "words", n: text.split(/\s+/).filter(Boolean).length }];
    case "lookup_numbers":
      if (/no registered value matches/.test(text)) return [{ k: "noMatch" }];
      return [{ k: "values", n: count(/ = /) }];
    case "search_evidence":
    case "recall_lessons":
    case "search_literature": {
      const n = count(/^- /);
      if (n) return [{ k: "results", n }];
      return /^no /.test(text) ? [{ k: "noResults" }] : line(48);
    }
    case "build_paper": {
      const pages = text.match(/main-text pages: (\d+) \(limit (\d+)\)/);
      const at = text.indexOf("gate findings:");
      const f = at >= 0 ? findings(text.slice(at)) : null;
      return [...(pages ? [{ k: "pages", n: Number(pages[1]), of: Number(pages[2]) } as OutcomePart] : []), ...(f ? [f] : [])];
    }
    case "lint": {
      const f = findings(text);
      return f ? [f] : line();
    }
    case "respond_to_finding":
      return call.args.action === "fixed" ? [{ k: "fixed" }] : call.args.action === "rebutted" ? [{ k: "rebutted" }] : [];
    case "update_todos":
      return [];
    default:
      return line();
  }
}

function view(call: AgentCall, at?: number): CallView {
  return {
    tool: call.tool,
    kind: kindOf(call.tool),
    target: targetOf(call),
    outcome: outcomeOf(call),
    ok: call.result ? call.result.ok : null,
    args: call.args,
    result: call.result?.text ?? "",
    at,
  };
}

function parseTodos(raw: string | undefined): Todo[] | null {
  if (!raw) return null;
  try {
    const list = JSON.parse(raw) as Array<Record<string, unknown>>;
    if (!Array.isArray(list)) return null;
    return list.map((t, i) => ({
      id: String(t.id ?? i + 1),
      content: String(t.content ?? t.text ?? t.title ?? t.task ?? ""),
      status: String(t.status ?? "pending"),
    }));
  } catch {
    return null;
  }
}

/** The feed of one transcript. Repeated calls are dropped, unchanged plans are not shown twice. */
export function buildFeed(items: AgentItem[]): FeedBlock[] {
  const out: FeedBlock[] = [];
  let lastPlan = "";
  const push = (block: FeedBlock) => out.push(block);
  const group = (call: CallView) => {
    const last = out[out.length - 1];
    if (last?.type === "group") last.calls.push(call);
    else push({ type: "group", calls: [call], at: call.at });
  };
  for (const item of items) {
    switch (item.kind) {
      case "task":
        push({ type: "task", text: item.text ?? "", at: item.at });
        break;
      case "assistant": {
        if (item.prose?.trim()) push({ type: "say", text: item.prose.trim(), at: item.at });
        if (item.error) push({ type: "error", text: item.error, at: item.at });
        for (const call of item.calls ?? []) {
          if (call.duplicate_of != null) continue;
          const v = view(call, item.at);
          if (v.kind === "plan") {
            const todos = call.result?.ok === false ? null : parseTodos(call.args.todos);
            const key = JSON.stringify(todos);
            if (todos && key !== lastPlan) {
              lastPlan = key;
              push({ type: "plan", todos, at: item.at });
            }
          } else if (LOOK_KINDS.has(v.kind) && v.ok !== false) {
            group(v);
          } else {
            push({ type: "change", call: v, at: item.at });
          }
        }
        break;
      }
      case "result":
        // A result the transcript could not pair with its call (older transcripts); show it as a look.
        group({
          tool: item.tool ?? "",
          kind: kindOf(item.tool ?? ""),
          target: "",
          outcome: firstLine(item.text ?? "") ? [{ k: "text", text: clip(firstLine(item.text ?? ""), 64) }] : [],
          ok: !!item.ok,
          args: {},
          result: item.text ?? "",
          at: item.at,
        });
        break;
      case "operator":
        push({ type: "operator", text: item.text ?? "", at: item.at });
        break;
      case "stop_blocked":
        push({ type: "handback", text: item.text ?? "", at: item.at });
        break;
      case "compact":
        push({ type: "compact", text: item.text ?? "", tokens: item.tokens_before ?? 0, at: item.at });
        break;
    }
  }
  return out;
}

/** Counts per kind in a group, for its header ("Read 2 sections, looked up 4 numbers"). */
export function groupCounts(calls: CallView[]): Array<[CallKind, number]> {
  const counts = new Map<CallKind, number>();
  for (const c of calls) counts.set(c.kind, (counts.get(c.kind) ?? 0) + 1);
  return [...counts.entries()];
}

/** The latest plan in a feed, for the status line ("Step 3 of 9 · Write the analysis section"). */
export function latestPlan(feed: FeedBlock[]): Todo[] | null {
  for (let i = feed.length - 1; i >= 0; i--) {
    const b = feed[i];
    if (b.type === "plan") return b.todos;
  }
  return null;
}

/** Head and tail of a long text with the number of hidden lines, like a terminal transcript. */
export function headTail(text: string, keep = 6): { head: string[]; hidden: number; tail: string[] } {
  const lines = text.split("\n");
  if (lines.length <= keep * 2 + 1) return { head: lines, hidden: 0, tail: [] };
  return { head: lines.slice(0, keep), hidden: lines.length - keep * 2, tail: lines.slice(-keep) };
}
