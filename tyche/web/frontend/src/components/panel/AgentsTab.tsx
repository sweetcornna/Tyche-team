import clsx from "clsx";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AgentSessionSummary } from "../../api/types";
import { useAsync } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { FeedView, sessionLabel } from "../run/AgentFeed";
import { PanelLoading, PanelMessage, type TabProps } from "./RightPanel";

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
                  <div className="truncate text-[12.5px] font-medium">{sessionLabel(s.name, t)}</div>
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
        ) : transcript.data ? (
          <FeedView transcript={transcript.data} live={false} />
        ) : null}
      </div>
    </div>
  );
}
