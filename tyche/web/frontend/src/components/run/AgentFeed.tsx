import clsx from "clsx";
import {
  AlertOctagon,
  Ban,
  BookOpen,
  Bot,
  Check,
  ChevronRight,
  Circle,
  FilePen,
  Globe,
  Hammer,
  Hash,
  Lightbulb,
  ListChecks,
  ListTodo,
  Loader2,
  MessageSquareReply,
  Minimize2,
  PencilLine,
  Search,
  Send,
  ShieldAlert,
  Type,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { AgentTranscript, RunEvent } from "../../api/types";
import { formatDuration, humanize } from "../../lib/format";
import { useTicker } from "../../lib/hooks";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { Markdown } from "../Markdown";
import {
  buildFeed,
  groupCounts,
  headTail,
  latestPlan,
  type CallView,
  type FeedBlock,
  type OutcomePart,
  type Todo,
} from "./feedModel";

type T = ReturnType<typeof useI18n>["t"];

/** The session whose work a stage shows: the planner while planning, the author while writing and revising. */
export const FEED_SESSION: Record<string, string> = { plan: "planner", write: "author", review: "author" };

export function sessionLabel(name: string, t: T): string {
  const key = `feed.session.${name}` as MessageKey;
  const label = t(key);
  return label === key ? humanize(name) : label;
}

/**
 * One agent session's transcript, refetched while it runs: after its events (at most every 1.5 s)
 * and every 20 s, so the thinking timer survives a restart of the pipeline process.
 */
export function useAgentTranscript(
  runId: string,
  stage: string | undefined,
  name: string | undefined,
  { live, events, enabled = true }: { live: boolean; events?: RunEvent[]; enabled?: boolean },
): AgentTranscript | null {
  const [data, setData] = useState<AgentTranscript | null>(null);
  const [tick, setTick] = useState(0);
  const last = useRef(0);
  const timer = useRef<number>();
  const agentEvents = useMemo(
    () => (events ?? []).filter((e) => e.kind.startsWith("agent.") || e.kind === "operator.delivered").length,
    [events],
  );

  useEffect(() => {
    if (!live || !enabled) return;
    const wait = Math.max(0, 1500 - (Date.now() - last.current));
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setTick((n) => n + 1), wait);
    return () => window.clearTimeout(timer.current);
  }, [agentEvents, live, enabled]);

  useEffect(() => {
    if (!live || !enabled) return;
    const id = window.setInterval(() => setTick((n) => n + 1), 20000);
    return () => window.clearInterval(id);
  }, [live, enabled]);

  useEffect(() => {
    if (!stage || !name || !enabled) return;
    let cancelled = false;
    last.current = Date.now();
    api
      .agentTranscript(runId, stage, name)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setData(null));
    return () => {
      cancelled = true;
    };
  }, [runId, stage, name, tick, enabled]);

  return data;
}

/* ---------- small pieces ---------- */

const KIND_ICONS: Record<string, ReactNode> = {
  read_section: <BookOpen />,
  read_material: <BookOpen />,
  paper_status: <ListChecks />,
  lint: <ListChecks />,
  check_plan: <ListChecks />,
  lookup_numbers: <Hash />,
  search_evidence: <Search />,
  search_literature: <Globe />,
  recall_lessons: <Lightbulb />,
  write_section: <FilePen />,
  edit_section: <PencilLine />,
  set_title: <Type />,
  build_paper: <Hammer />,
  respond_to_finding: <MessageSquareReply />,
  delegate: <Bot />,
  submit_plan: <Send />,
  submit: <Send />,
};

function ToolIcon({ tool }: { tool: string }) {
  return <span className="flex h-4 w-4 shrink-0 items-center justify-center text-faint [&>svg]:h-[15px] [&>svg]:w-[15px]">{KIND_ICONS[tool] ?? <Wrench />}</span>;
}

export function formatOutcome(parts: OutcomePart[], t: T): string {
  const out: string[] = [];
  for (const p of parts) {
    switch (p.k) {
      case "words":
        out.push(t("feed.out.words", { n: p.n }));
        break;
      case "noFindings":
        out.push(t("feed.out.noFindings"));
        break;
      case "findings":
        if (p.blocker) out.push(t("feed.out.blocker", { n: p.blocker }));
        if (p.major) out.push(t("feed.out.major", { n: p.major }));
        if (p.minor) out.push(t("feed.out.minor", { n: p.minor }));
        break;
      case "notWritten":
        out.push(t("feed.out.notWritten"));
        break;
      case "values":
        out.push(t("feed.out.values", { n: p.n }));
        break;
      case "noMatch":
        out.push(t("feed.out.noMatch"));
        break;
      case "results":
        out.push(t("feed.out.results", { n: p.n }));
        break;
      case "noResults":
        out.push(t("feed.out.noResults"));
        break;
      case "pages":
        out.push(t("feed.out.pages", { n: p.n, of: p.of }));
        break;
      case "fixed":
        out.push(t("feed.out.fixed"));
        break;
      case "rebutted":
        out.push(t("feed.out.rebutted"));
        break;
      case "text":
        out.push(p.text);
        break;
    }
  }
  return out.join(" · ");
}

function severityTone(parts: OutcomePart[]): string {
  const f = parts.find((p) => p.k === "findings") as Extract<OutcomePart, { k: "findings" }> | undefined;
  if (f?.blocker) return "text-bad";
  if (f?.major) return "text-warn";
  return "text-faint";
}

/** A monospace block that shows the head and tail of long text and expands on demand. */
function Output({ text, tone }: { text: string; tone?: "error" }) {
  const { t } = useI18n();
  const [all, setAll] = useState(false);
  const { head, hidden, tail } = headTail(text, 6);
  return (
    <pre
      className={clsx(
        "max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg px-3 py-2 font-mono text-[12px] leading-[1.6]",
        tone === "error" ? "bg-bad/[0.06] text-bad" : "bg-subtle/[0.045] text-muted",
      )}
    >
      {all || !hidden ? (
        text
      ) : (
        <>
          {head.join("\n")}
          {"\n"}
          <button onClick={() => setAll(true)} className="my-0.5 font-sans text-[12px] font-medium text-info hover:underline">
            {t("feed.hiddenLines", { n: hidden })}
          </button>
          {"\n"}
          {tail.join("\n")}
        </>
      )}
    </pre>
  );
}

/** Arguments worth showing in full (LaTeX, long queries); short ones are already in the row. */
function LongArgs({ call }: { call: CallView }) {
  const long = Object.entries(call.args).filter(([k, v]) => v.length > 60 || v.includes("\n") || (call.tool === "edit_section" && (k === "old" || k === "new")));
  if (!long.length) return null;
  if (call.tool === "edit_section" && call.args.old != null) {
    return (
      <div className="overflow-hidden rounded-lg bg-subtle/[0.045] font-mono text-[12px] leading-[1.6]">
        {call.args.old.split("\n").map((l, i) => (
          <div key={`o${i}`} className="whitespace-pre-wrap break-words bg-bad/[0.07] px-3 text-bad">
            − {l}
          </div>
        ))}
        {(call.args.new ?? "").split("\n").map((l, i) => (
          <div key={`n${i}`} className="whitespace-pre-wrap break-words bg-ok/[0.08] px-3 text-ok">
            + {l}
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {long.map(([k, v]) => (
        <div key={k}>
          <div className="mb-0.5 font-mono text-[11px] text-faint">{k}</div>
          <Output text={v} />
        </div>
      ))}
    </div>
  );
}

/** One call: icon, verb, target, and its one-line outcome; click for the arguments and the output. */
function CallRow({ call, prominent = false }: { call: CallView; prominent?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const verbKey = `feed.verb.${call.tool}` as MessageKey;
  const verb = t(verbKey) === verbKey ? `${t("feed.verb.other")} ${call.tool}` : t(verbKey);
  const outcome = call.ok === null ? t("feed.notRun") : formatOutcome(call.outcome, t);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={clsx(
          "group flex w-full min-w-0 items-center gap-2 rounded-md px-1.5 py-[3px] text-left hover:bg-subtle/[0.05]",
          prominent ? "text-[14px]" : "text-[13.5px]",
        )}
      >
        {call.ok === false ? <Ban className="h-[15px] w-[15px] shrink-0 text-faint" /> : <ToolIcon tool={call.tool} />}
        <span className={clsx("shrink-0", prominent ? "font-medium text-fg" : "text-fg")}>{verb}</span>
        {call.target && (
          <span className={clsx("min-w-0 truncate", call.kind === "lookup" || call.kind === "search" ? "font-mono text-[12.5px] text-muted" : "text-muted")}>
            {call.kind === "search" ? `“${call.target}”` : call.target}
          </span>
        )}
        <span className="flex-1" />
        {outcome && (
          <span className={clsx("shrink-0 truncate pl-2 text-right text-[12.5px] tabular-nums", call.ok === false ? "text-faint" : severityTone(call.outcome))}>
            {outcome}
          </span>
        )}
        <ChevronRight className={clsx("h-3.5 w-3.5 shrink-0 text-faint opacity-0 transition group-hover:opacity-100", open && "rotate-90 opacity-100")} />
      </button>
      {open && (
        <div className="mb-2 ml-7 mt-1 space-y-2">
          <LongArgs call={call} />
          {call.result && <Output text={call.result} tone={call.ok === false ? "error" : undefined} />}
        </div>
      )}
    </div>
  );
}

/** Consecutive look-ups folded under one summary line, like "Read 2, looked up 4 numbers". */
function CallGroup({ calls, defaultOpen }: { calls: CallView[]; defaultOpen: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => setOpen(defaultOpen), [defaultOpen]);
  const summary = groupCounts(calls)
    .map(([kind, n]) => t(`feed.group.${["read", "lookup", "search", "check"].includes(kind) ? kind : "other"}` as MessageKey, { n }))
    .join(t("feed.sep"));
  const failed = calls.filter((c) => c.ok === false).length;
  return (
    <div className="rounded-[14px] bg-subtle/[0.035] px-1.5 py-1">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13.5px] text-muted hover:text-fg">
        <Search className="h-[15px] w-[15px] shrink-0 text-faint" />
        <span className="min-w-0 truncate">{summary.charAt(0).toUpperCase() + summary.slice(1)}</span>
        <ChevronRight className={clsx("h-3.5 w-3.5 shrink-0 text-faint transition-transform", open && "rotate-90")} />
        <span className="flex-1" />
        <span className="shrink-0 text-[12px] tabular-nums text-faint">
          {t("feed.steps", { n: calls.length })}
          {failed > 0 && ` · ${t("feed.failed", { n: failed })}`}
        </span>
      </button>
      {open && (
        <div className="pb-0.5 pl-1">
          {calls.map((c, i) => (
            <CallRow key={i} call={c} />
          ))}
        </div>
      )}
    </div>
  );
}

export function PlanList({ todos, live = false, compact = false }: { todos: Todo[]; live?: boolean; compact?: boolean }) {
  return (
    <ul className={clsx("space-y-0.5", compact ? "text-[13px]" : "text-[13.5px]")}>
      {todos.map((x) => (
        <li key={x.id} className="flex items-start gap-2">
          {x.status === "completed" ? (
            <Check className="mt-[3px] h-3.5 w-3.5 shrink-0 text-ok" />
          ) : x.status === "in_progress" ? (
            <Loader2 className={clsx("mt-[3px] h-3.5 w-3.5 shrink-0 text-info", live && "animate-spin")} />
          ) : (
            <Circle className="mt-[3px] h-3.5 w-3.5 shrink-0 text-faint" />
          )}
          <span
            className={clsx(
              x.status === "completed" && "text-faint line-through decoration-line/30",
              x.status === "in_progress" && "font-medium text-fg",
              x.status === "pending" && "text-muted",
              x.status === "cancelled" && "text-faint line-through",
            )}
          >
            {x.content}
          </span>
        </li>
      ))}
    </ul>
  );
}

function PlanCell({ todos, live }: { todos: Todo[]; live: boolean }) {
  const { t } = useI18n();
  const done = todos.filter((x) => x.status === "completed").length;
  return (
    <div className="px-1.5">
      <div className="mb-1 flex items-center gap-2 text-[13.5px] text-muted">
        <ListTodo className="h-[15px] w-[15px] text-faint" />
        {t("feed.plan")}
        <span className="text-[12px] text-faint">· {t("feed.planProgress", { done, n: todos.length })}</span>
      </div>
      <div className="ml-6">
        <PlanList todos={todos} live={live} compact />
      </div>
    </div>
  );
}

function Collapsible({ label, icon, tone, children }: { label: ReactNode; icon: ReactNode; tone?: "warn" | "info"; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={clsx(
          "flex w-full items-center gap-2 rounded-md px-1.5 py-[3px] text-left text-[13.5px] hover:bg-subtle/[0.05] [&>svg:first-child]:h-[15px] [&>svg:first-child]:w-[15px]",
          tone === "warn" ? "text-warn" : tone === "info" ? "text-info" : "text-muted",
        )}
      >
        {icon}
        <span className="min-w-0 truncate">{label}</span>
        <ChevronRight className={clsx("h-3.5 w-3.5 shrink-0 opacity-60 transition-transform", open && "rotate-90")} />
      </button>
      {open && <div className="mb-2 ml-7 mt-1">{children}</div>}
    </div>
  );
}

function Block({ block, last, live }: { block: FeedBlock; last: boolean; live: boolean }) {
  const { t } = useI18n();
  switch (block.type) {
    case "task":
      return (
        <Collapsible icon={<ListTodo />} label={`${t("feed.task")} · ${block.text.split("\n")[0].slice(0, 120)}`}>
          <Output text={block.text} />
        </Collapsible>
      );
    case "say":
      return (
        <div className="px-1.5 text-[15px] leading-7 text-fg [&_p]:my-1.5">
          <Markdown text={block.text} />
        </div>
      );
    case "group":
      return <CallGroup calls={block.calls} defaultOpen={last && live} />;
    case "change":
      return <CallRow call={block.call} prominent />;
    case "plan":
      return <PlanCell todos={block.todos} live={live && last} />;
    case "operator":
      return (
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-3xl bg-bubble px-4 py-2 text-[15px] leading-6 sm:max-w-[70%]">
            <div className="mb-0.5 text-[11.5px] font-medium text-faint">{t("feed.you")}</div>
            <div className="whitespace-pre-wrap break-words">{block.text}</div>
          </div>
        </div>
      );
    case "handback":
      return (
        <Collapsible icon={<ShieldAlert />} tone="warn" label={t("agents.handback")}>
          <Output text={block.text} />
        </Collapsible>
      );
    case "compact":
      return (
        <Collapsible icon={<Minimize2 />} tone="info" label={t("agents.compacted", { n: block.tokens })}>
          <Output text={block.text} />
        </Collapsible>
      );
    case "error":
      return (
        <div className="flex items-center gap-2 px-1.5 text-[13.5px] text-faint">
          <AlertOctagon className="h-[15px] w-[15px]" />
          {t("feed.error")}
        </div>
      );
  }
}

/** A session's activity: what the agent said, folded look-ups, its edits, plan updates, and hand-backs. */
export function FeedView({ transcript, live }: { transcript: AgentTranscript; live: boolean }) {
  const { t } = useI18n();
  const feed = useMemo(() => buildFeed(transcript.items), [transcript.items]);
  if (!feed.length) return <div className="px-1.5 text-[13.5px] text-faint">{t("feed.waitingFirst")}</div>;
  return (
    <div className="space-y-1.5">
      {feed.map((b, i) => (
        <Block key={i} block={b} last={i === feed.length - 1 || (i === feed.length - 2 && feed[feed.length - 1].type !== "group")} live={live} />
      ))}
    </div>
  );
}

/** The live status line: which agent is thinking, for how long, and the step it is on. */
export function AgentStatus({ transcript, session }: { transcript: AgentTranscript | null; session: string }) {
  const { t } = useI18n();
  useTicker(true);
  const waiting = transcript?.waiting_since ?? null;
  const plan = transcript ? latestPlan(buildFeed(transcript.items)) : null;
  const step = plan?.find((x) => x.status === "in_progress");
  const done = plan?.filter((x) => x.status === "completed").length ?? 0;
  const seconds = waiting != null ? Math.max(0, Date.now() / 1000 - waiting) : null;
  return (
    <div className="space-y-0.5">
      <div className="flex min-w-0 items-center gap-2 text-[13.5px]">
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-info/50" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-info" />
        </span>
        <span className="shimmer-text shrink-0 font-medium">{t("feed.thinking", { session: sessionLabel(session, t) })}</span>
        {seconds != null && <span className="shrink-0 tabular-nums text-faint">{formatDuration(seconds, t)}</span>}
        {plan && plan.length > 0 && (
          <span className="min-w-0 truncate text-faint">
            · {done}/{plan.length}
            {step && ` · ${step.content}`}
          </span>
        )}
      </div>
      {seconds != null && seconds > 600 && <div className="pl-4 text-[12px] text-faint">{t("feed.slow")}</div>}
    </div>
  );
}

/** A finished session, folded to "Worked for 1h 20m · 42 tool calls"; the feed loads when opened. */
export function AgentWork({ runId, stage, session, seconds }: { runId: string; stage: string; session: string; seconds?: number | null }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const transcript = useAgentTranscript(runId, stage, session, { live: false, enabled: true });
  if (!transcript || !transcript.items.length) return null;
  const calls = transcript.items.reduce((n, i) => n + (i.calls?.filter((c) => c.duplicate_of == null).length ?? 0), 0);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 text-[13px] text-faint hover:text-muted"
      >
        <span className="h-px flex-1 bg-line/[0.08]" />
        <span className="flex shrink-0 items-center gap-1">
          {seconds ? t("feed.worked", { time: formatDuration(seconds, t), calls }) : t("feed.workedShort", { calls })}
          <ChevronRight className={clsx("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
        </span>
        <span className="h-px flex-1 bg-line/[0.08]" />
      </button>
      {open && (
        <div className="mt-2">
          <FeedView transcript={transcript} live={false} />
        </div>
      )}
    </div>
  );
}
