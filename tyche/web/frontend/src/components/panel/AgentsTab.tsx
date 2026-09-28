import clsx from "clsx";
import { ArrowUpLeft, Bot, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { FeedView, sessionLabel } from "../run/AgentFeed";
import { Badge, Button, IconButton } from "../ui";
import { PanelLoading, PanelMessage, type TabProps } from "./RightPanel";

/** Every agent session of the run (planner, author, helpers, reviewers) with its full transcript. */
export default function AgentsTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const live = detail.status === "running";
  const list = useAsync(() => api.agents(runId), [runId, detail.updated_at], { interval: live ? 2500 : undefined });
  const sessions = list.data ?? [];
  const [selectedKey, setSelectedKey] = useState("");
  useEffect(() => setSelectedKey(""), [runId]);
  const sel = sessions.find((s) => `${s.stage}/${s.name}` === selectedKey) ?? sessions.find((s) => s.status === "running") ?? sessions[0];
  const active = !!sel && live && (sel.status === "running" || sel.status === "delegating");
  useEffect(() => {
    if (!selectedKey && sel) setSelectedKey(`${sel.stage}/${sel.name}`);
  }, [sel, selectedKey]);
  const transcript = useAsync(
    () => (sel ? api.agentTranscript(runId, sel.stage, sel.name) : Promise.resolve(null)),
    [runId, sel?.stage, sel?.name, sel?.last_activity, detail.updated_at],
    { interval: active ? 2500 : undefined },
  );

  if (list.loading && !list.data) return <PanelLoading />;
  if (list.error && !list.data) return <PanelMessage><p role="alert">{list.error.message}</p><Button onClick={list.reload}>{t("model.refresh")}</Button></PanelMessage>;
  if (!sessions.length) return <PanelMessage>{t("agents.none")}</PanelMessage>;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="agents-panel">
      <div className="flex shrink-0 items-center justify-between border-b border-line/[0.08] px-3 py-2 text-xs text-muted">
        <span>{t("agents.teamStats", { n: sessions.length, active: sessions.filter((s) => ["running", "delegating"].includes(s.status)).length })}</span>
        <IconButton label={t("model.refresh")} size="sm" onClick={() => { list.reload(); transcript.reload(); }}><RefreshCw className="h-3.5 w-3.5" /></IconButton>
      </div>
      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
      <nav aria-label={t("panel.agents")} className="max-h-[190px] shrink-0 overflow-y-auto border-b border-line/[0.06] py-2 sm:max-h-none sm:w-[38%] sm:min-w-[140px] sm:max-w-[230px] sm:border-b-0 sm:border-r">
        {(["plan", "write", "review"] as const).map((stage) => {
          const items = sessions.filter((s) => s.stage === stage);
          if (!items.length) return null;
          return (
            <div key={stage} className="mb-2">
              <div className="px-3 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">{t(`stage.${stage}`)}</div>
              {items.map((s) => (
                <button
                  key={`${s.stage}/${s.name}`}
                  onClick={() => setSelectedKey(`${s.stage}/${s.name}`)}
                  aria-pressed={sel?.stage === s.stage && sel.name === s.name}
                  data-testid="agents-session" data-variant={`${s.stage}/${s.name}`}
                  className={clsx(
                    "block w-full px-3 py-1.5 text-left",
                    sel?.stage === s.stage && sel.name === s.name ? "bg-subtle/[0.07] text-fg" : "text-muted hover:bg-subtle/[0.04] hover:text-fg",
                  )}
                >
                  <div className="flex min-w-0 items-center gap-1.5 text-[12.5px] font-medium">
                    <Bot className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{sessionLabel(s.session, t)}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-1.5 text-[11px]">
                    <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", ["running", "delegating"].includes(s.status) ? "animate-pulse bg-accent" : s.status === "done" ? "bg-ok" : "bg-warn")} />
                    <span>{t(`agents.status.${s.status}`)}</span>
                  </div>
                  <div className="mt-1 truncate text-[11px] text-muted" title={s.model ?? undefined}>{s.model ?? t("agents.modelUnknown")}</div>
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
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pb-10 pt-3">
        {sel && <div className="mb-4 border-b border-line/[0.08] pb-3" data-testid="agents-session-detail">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
            {sessionLabel(sel.session, t)}<Badge tone={sel.status === "done" ? "ok" : active ? "neutral" : "warn"}>{t(`agents.status.${sel.status}`)}</Badge>
          </div>
          <p className="mt-1 break-all text-xs text-muted">{sel.model ?? t("agents.modelUnknown")}{sel.provider ? ` · ${sel.provider}` : ""}</p>
          <p className="mt-1 break-all text-[11px] text-faint">{sel.name}</p>
          {sel.parent_session && <button className="mt-2 flex items-center gap-1 text-xs text-accent"
            onClick={() => setSelectedKey(`${sel.stage}/${sel.parent_session}`)}>
            <ArrowUpLeft className="h-3.5 w-3.5" />{sessionLabel(sel.parent_session, t)}
          </button>}
          {sel.tool_errors > 0 && <p className="mt-1 text-xs text-warn">{t("agents.toolErrors", { n: sel.tool_errors })}</p>}
        </div>}
        {transcript.error ? <p role="alert" className="text-xs text-warn">{transcript.error.message}</p> : null}
        {transcript.loading && (!transcript.data || transcript.data.stage !== sel?.stage || transcript.data.name !== sel?.name) ? (
          <PanelLoading />
        ) : transcript.data?.stage === sel?.stage && transcript.data?.name === sel?.name ? (
          <FeedView transcript={transcript.data} live={active} />
        ) : null}
      </div>
      </div>
    </div>
  );
}
