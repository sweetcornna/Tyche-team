import clsx from "clsx";
import { AlertOctagon, Check, ChevronRight, FileText, ListTodo, ShieldAlert, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AgentItem, AgentSessionSummary } from "../../api/types";
import { humanize } from "../../lib/format";
import { useAsync } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { PanelLoading, PanelMessage, type TabProps } from "./RightPanel";

const LONG = 600;

/** A block of text that starts clipped and expands on demand. */
function Clipped({ text, mono = false }: { text: string; mono?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const long = text.length > LONG;
  return (
    <div>
      <div className={clsx("whitespace-pre-wrap break-words", mono ? "font-mono text-[12px] leading-[1.6]" : "text-[13.5px] leading-6")}>
        {long && !open ? text.slice(0, LONG) + " …" : text}
      </div>
      {long && (
        <button onClick={() => setOpen((v) => !v)} className="mt-1 text-[12px] font-medium text-info hover:underline">
          {open ? t("agents.less") : t("agents.more")}
        </button>
      )}
    </div>
  );
}

function CallChip({ tool, args }: { tool: string; args: Record<string, string> }) {
  const [open, setOpen] = useState(false);
  const short = Object.entries(args)
    .filter(([, v]) => v.length <= 40 && !v.includes("\n"))
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");
  const big = Object.entries(args).filter(([, v]) => v.length > 40 || v.includes("\n"));
  return (
    <div className="rounded-lg border border-line/10">
      <button
        onClick={() => big.length && setOpen((v) => !v)}
        className={clsx("flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left font-mono text-[12px]", big.length ? "cursor-pointer" : "cursor-default")}
      >
        <Wrench className="h-3 w-3 shrink-0 text-faint" />
        <span className="font-semibold text-fg">{tool}</span>
        {short && <span className="truncate text-muted">({short})</span>}
        {big.length > 0 && <ChevronRight className={clsx("ml-auto h-3 w-3 shrink-0 text-faint transition-transform", open && "rotate-90")} />}
      </button>
      {open && (
        <div className="space-y-2 border-t border-line/[0.06] px-2.5 py-2">
          {big.map(([k, v]) => (
            <div key={k}>
              <div className="mb-0.5 text-[11px] uppercase tracking-wide text-faint">{k}</div>
              <Clipped text={v} mono />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Item({ item }: { item: AgentItem }) {
  const { t } = useI18n();
  if (item.kind === "task") {
    return (
      <div className="rounded-xl bg-subtle/[0.05] px-3 py-2">
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
          <ListTodo className="h-3.5 w-3.5" /> {t("agents.task")}
        </div>
        <Clipped text={item.text ?? ""} />
      </div>
    );
  }
  if (item.kind === "assistant") {
    return (
      <div className="space-y-1.5">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">{t("agents.turn", { n: item.turn ?? 0 })}</div>
        {item.prose && <Clipped text={item.prose} />}
        {item.error && <div className="text-[12.5px] text-bad">{item.error}</div>}
        {(item.calls ?? []).map((c, i) => (
          <CallChip key={i} tool={c.tool} args={c.args} />
        ))}
      </div>
    );
  }
  if (item.kind === "result") {
    return (
      <div className="ml-3 border-l-2 border-line/10 pl-3">
        <div className="mb-0.5 flex items-center gap-1.5 font-mono text-[11.5px] text-faint">
          {item.ok ? <Check className="h-3 w-3 text-ok" /> : <AlertOctagon className="h-3 w-3 text-bad" />}
          {item.tool}
        </div>
        <Clipped text={item.text ?? ""} mono />
      </div>
    );
  }
  if (item.kind === "stop_blocked") {
    return (
      <div className="rounded-xl border border-warn/30 bg-warn/[0.06] px-3 py-2">
        <div className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold text-warn">
          <ShieldAlert className="h-3.5 w-3.5" /> {t("agents.handback")}
        </div>
        <Clipped text={item.text ?? ""} mono />
      </div>
    );
  }
  if (item.kind === "compact") {
    return (
      <div className="rounded-xl border border-info/30 bg-info/[0.05] px-3 py-2">
        <div className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold text-info">
          <FileText className="h-3.5 w-3.5" /> {t("agents.compacted", { n: item.tokens_before ?? 0 })}
        </div>
        <Clipped text={item.text ?? ""} />
      </div>
    );
  }
  return null;
}

/** Every agent session of the run (planner, author, helpers, reviewers) with its full transcript. */
export default function AgentsTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const list = useAsync(() => api.agents(runId), [runId, detail.updated_at]);
  const sessions = list.data ?? [];
  const [sel, setSel] = useState<AgentSessionSummary | null>(null);
  useEffect(() => {
    if (!sel && sessions.length) setSel(sessions.find((s) => s.session === "author") ?? sessions[0]);
  }, [sel, sessions]);
  const transcript = useAsync(
    () => (sel ? api.agentTranscript(runId, sel.stage, sel.name) : Promise.resolve(null)),
    [runId, sel?.stage, sel?.name, sel?.turns, detail.updated_at],
  );

  if (list.loading && !list.data) return <PanelLoading />;
  if (!sessions.length) return <PanelMessage>{t("agents.none")}</PanelMessage>;

  return (
    <div className="flex h-full min-h-0">
      <nav className="w-[38%] min-w-[170px] max-w-[250px] shrink-0 overflow-y-auto border-r border-line/[0.06] py-2">
        {(["plan", "write", "review"] as const).map((stage) => {
          const items = sessions.filter((s) => s.stage === stage);
          if (!items.length) return null;
          return (
            <div key={stage} className="mb-2">
              <div className="px-3 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">{t(`stage.${stage}`)}</div>
              {items.map((s) => (
                <button
                  key={`${s.stage}/${s.name}`}
                  onClick={() => setSel(s)}
                  className={clsx(
                    "block w-full px-3 py-1.5 text-left",
                    sel?.stage === s.stage && sel.name === s.name ? "bg-subtle/[0.07] text-fg" : "text-muted hover:bg-subtle/[0.04] hover:text-fg",
                  )}
                >
                  <div className="truncate text-[12.5px] font-medium">{humanize(s.name)}</div>
                  <div className="text-[11px] text-faint">
                    {t("agents.stats", { turns: s.turns, calls: s.tool_calls })}
                    {s.handbacks > 0 && ` · ${t("agents.handbacks", { n: s.handbacks })}`}
                  </div>
                </button>
              ))}
            </div>
          );
        })}
      </nav>
      <div className="min-w-0 flex-1 overflow-y-auto px-4 pb-10 pt-3">
        {transcript.loading && !transcript.data ? (
          <PanelLoading />
        ) : (
          <div className="space-y-3">
            {(transcript.data?.items ?? []).map((item, i) => (
              <Item key={i} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
