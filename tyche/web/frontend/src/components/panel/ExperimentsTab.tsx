import clsx from "clsx";
import { AlertOctagon, Check, File, Folder, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import type { ExperimentEvent } from "../../api/types";
import { formatBytes, formatMetric, humanize } from "../../lib/format";
import { useAsync } from "../../lib/hooks";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { CodeView, languageForPath, Markdown } from "../Markdown";
import { Badge, Segmented } from "../ui";
import { PanelLoading, PanelMessage, PanelScroll, type TabProps } from "./RightPanel";

type View = "design" | "timeline" | "code" | "metrics" | "reflections";

export default function ExperimentsTab({ runId, detail, experimentEvents }: TabProps) {
  const { t } = useI18n();
  const stage = detail.stages.find((s) => s.name === "experiments");
  const running = stage?.status === "running";
  const info = useAsync(() => api.experiments(runId), [runId, stage?.status], { interval: running ? 10000 : undefined });
  const [view, setView] = useState<View>("design");
  const data = info.data;

  const timeline = useMemo(() => {
    const base = data?.timeline ?? [];
    const seen = new Set(base.map((e) => `${e.attempt}|${e.ts}|${e.event}`));
    return [...base, ...experimentEvents.filter((e) => !seen.has(`${e.attempt}|${e.ts}|${e.event}`))];
  }, [data, experimentEvents]);

  if (info.loading && !data) return <PanelLoading />;
  if (!data || data.status === "pending") return <PanelMessage>{t("panel.unavailable")}</PanelMessage>;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-5 pb-3 pt-4">
        <Segmented<View>
          value={view}
          onChange={setView}
          options={[
            { value: "design", label: t("exp.designShort") },
            { value: "timeline", label: t("exp.timelineShort") },
            { value: "code", label: t("exp.codeShort") },
            { value: "metrics", label: t("exp.metrics") },
            { value: "reflections", label: t("exp.reflectionsShort") },
          ]}
        />
        <div className="flex-1" />
        <Badge tone={data.status === "completed" ? "ok" : data.status === "failed" ? "bad" : "info"}>{data.engine}</Badge>
        {data.synthetic && <Badge tone="warn">{t("run.synthetic")}</Badge>}
      </div>
      <div className="min-h-0 flex-1 border-t border-line/[0.06]">
        {view === "design" &&
          (data.design_md ? (
            <PanelScroll>
              <Markdown text={data.design_md} />
            </PanelScroll>
          ) : (
            <PanelMessage>{data.notes || t("panel.unavailable")}</PanelMessage>
          ))}
        {view === "timeline" && <Timeline events={timeline} live={running ? data.live : null} />}
        {view === "code" && <CodeBrowser runId={runId} files={data.files} root={data.files_root} />}
        {view === "metrics" && <Metrics metrics={data.metrics} />}
        {view === "reflections" &&
          (data.reflections.length ? (
            <PanelScroll className="space-y-6">
              {data.reflections.map((r) => (
                <section key={r.name}>
                  <div className="mb-2 font-mono text-xs text-faint">{r.name}</div>
                  <Markdown text={r.text} compact />
                </section>
              ))}
            </PanelScroll>
          ) : (
            <PanelMessage>{t("panel.empty")}</PanelMessage>
          ))}
      </div>
    </div>
  );
}

function Timeline({ events, live }: { events: ExperimentEvent[]; live: { module: string; round: number; model_calls: number } | null }) {
  const { t } = useI18n();
  const rows = events.filter((e) => e.event === "subagent_finish" || e.event === "module_report" || /abort|fail|complete|terminal/.test(e.event));
  // module_report duplicates subagent_finish; keep one row per (attempt, module, round).
  const unique = rows.filter(
    (e, i) => e.event !== "module_report" || !rows.some((o, j) => j < i && o.event === "subagent_finish" && o.module === e.module && o.round === e.round && o.attempt === e.attempt),
  );
  if (!unique.length && !live) return <PanelMessage>{t("panel.empty")}</PanelMessage>;
  return (
    <PanelScroll>
      <ol className="relative ml-2 border-l border-line/10">
        {unique.map((e, i) => {
          const failed = e.outcome === "failed" || /abort|fail/.test(e.event);
          return (
            <li key={`${e.attempt}-${e.ts}-${i}`} className="relative pb-4 pl-5">
              <span className={clsx("absolute -left-[7px] top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full ring-4 ring-main", failed ? "bg-bad" : "bg-ok")}>
                {failed ? <AlertOctagon className="h-2.5 w-2.5 text-white" /> : <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
              </span>
              <div className="text-[13.5px] font-medium">
                {e.module ? t(`exp.module.${e.module}` as MessageKey, {}) : humanize(e.event)}
                {e.round != null && <span className="ml-1.5 font-normal text-faint">· {t("exp.round", { n: e.round })}</span>}
              </div>
              <div className="mt-0.5 text-xs text-faint">
                {new Date(e.ts).toLocaleTimeString()} · {e.attempt}
                {e.outcome && ` · ${t(`exp.outcome.${e.outcome}` as MessageKey)}`}
              </div>
            </li>
          );
        })}
        {live && (
          <li className="relative pl-5">
            <span className="absolute -left-[7px] top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-info ring-4 ring-main">
              <Loader2 className="h-2.5 w-2.5 animate-spin text-white" />
            </span>
            <div className="shimmer-text text-[13.5px] font-medium">{t(`exp.module.${live.module}` as MessageKey)}</div>
            <div className="mt-0.5 text-xs text-faint">
              {t("exp.round", { n: live.round })} · {t("exp.liveCalls", { n: live.model_calls })}
            </div>
          </li>
        )}
      </ol>
    </PanelScroll>
  );
}

function CodeBrowser({ runId, files, root }: { runId: string; files: { path: string; size: number }[]; root: string | null }) {
  const { t } = useI18n();
  const sorted = useMemo(() => [...files].sort((a, b) => a.path.localeCompare(b.path)), [files]);
  const first = sorted.find((f) => /\.(py|md)$/.test(f.path))?.path ?? sorted[0]?.path ?? null;
  const [selected, setSelected] = useState<string | null>(first);
  const file = useAsync(() => (selected ? api.experimentFile(runId, selected) : Promise.resolve("")), [runId, selected], { enabled: !!selected });
  if (!files.length) return <PanelMessage>{t("exp.noCode")}</PanelMessage>;
  return (
    <div className="flex h-full min-h-0">
      <nav className="w-[36%] min-w-[150px] max-w-[240px] shrink-0 overflow-y-auto border-r border-line/[0.06] py-2">
        {root && <div className="px-3 pb-1.5 text-[11px] font-medium uppercase tracking-wide text-faint">{root === "live" ? t("exp.liveFiles") : t("exp.archivedFiles")}</div>}
        {sorted.map((f) => {
          const depth = f.path.split("/").length - 1;
          return (
            <button
              key={f.path}
              onClick={() => setSelected(f.path)}
              title={`${f.path} · ${formatBytes(f.size)}`}
              className={clsx(
                "flex w-full items-center gap-1.5 truncate py-1 pr-2 text-left font-mono text-[12px]",
                selected === f.path ? "bg-subtle/[0.07] text-fg" : "text-muted hover:bg-subtle/[0.04] hover:text-fg",
              )}
              style={{ paddingLeft: 12 + depth * 10 }}
            >
              {f.path.endsWith("/") ? <Folder className="h-3.5 w-3.5 shrink-0" /> : <File className="h-3.5 w-3.5 shrink-0 text-faint" />}
              <span className="truncate">{f.path.split("/").pop()}</span>
            </button>
          );
        })}
      </nav>
      <div className="min-w-0 flex-1 overflow-auto">
        {!selected ? (
          <PanelMessage>{t("exp.selectFile")}</PanelMessage>
        ) : file.loading && file.data == null ? (
          <PanelLoading />
        ) : file.error ? (
          <PanelMessage>{file.error.message}</PanelMessage>
        ) : (
          <>
            <div className="sticky top-0 z-[1] border-b border-line/[0.06] bg-main/95 px-4 py-2 font-mono text-[11.5px] text-faint backdrop-blur">{selected}</div>
            <CodeView code={file.data ?? ""} language={languageForPath(selected)} />
          </>
        )}
      </div>
    </div>
  );
}

function Metrics({ metrics }: { metrics: Record<string, Record<string, number>> }) {
  const { t } = useI18n();
  const variants = Object.keys(metrics);
  const names = useMemo(() => {
    const s = new Set<string>();
    variants.forEach((v) => Object.keys(metrics[v]).forEach((k) => s.add(k)));
    return [...s];
  }, [metrics, variants]);
  if (!variants.length) return <PanelMessage>{t("panel.empty")}</PanelMessage>;
  return (
    <PanelScroll>
      <p className="mb-3 text-xs text-faint">{t("exp.metricsNote")}</p>
      <div className="overflow-x-auto rounded-2xl border border-line/10">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("exp.variants")}</th>
              {names.map((n) => (
                <th key={n} className="num">
                  {humanize(n)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {variants.map((v) => (
              <tr key={v}>
                <td className={clsx(v === "proposed" && "font-semibold")}>{v}</td>
                {names.map((n) => (
                  <td key={n} className="num">
                    {formatMetric(metrics[v][n])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelScroll>
  );
}
