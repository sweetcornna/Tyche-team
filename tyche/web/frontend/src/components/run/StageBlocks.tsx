import clsx from "clsx";
import {
  AlertOctagon,
  ArrowUpRight,
  Check,
  ChevronRight,
  Circle,
  Download,
  ExternalLink,
  FileText,
  FlaskConical,
  Loader2,
  PauseCircle,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { api, files } from "../../api/client";
import type { ExperimentEvent, RunDetail, RunEvent, StageInfo, StageName } from "../../api/types";
import { elapsedSince, formatDuration, formatMetric, formatTokens, humanize } from "../../lib/format";
import { useAsync, useTicker } from "../../lib/hooks";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { RoundTrend, ScoreBars } from "../charts";
import { Badge, Button } from "../ui";

export type OpenPanel = (tab: string) => void;

/** A stage as shown in the conversation; `interrupted` marks a "running" stage whose process is gone. */
export type ViewStage = StageInfo & { interrupted?: boolean };

/* ---------- Stage wrapper: "Planned the study · 4m 18s ›" ---------- */

export function StageBlock({
  stage,
  children,
  details,
  live,
}: {
  stage: ViewStage;
  children?: ReactNode;
  details?: ReactNode;
  live?: ReactNode;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const running = stage.status === "running" && !stage.interrupted;
  useTicker(running);
  const duration = running ? elapsedSince(stage.running_at) : stage.interrupted ? null : stage.duration_s ?? null;
  const title = stage.interrupted
    ? `${t(`stage.${stage.name}` as MessageKey)} — ${t("stage.interrupted")}`
    : running
      ? t(`stageDoing.${stage.name}` as MessageKey)
      : stage.status === "failed"
        ? `${t(`stage.${stage.name}` as MessageKey)} — ${t("stage.failed")}`
        : t(`stageDone.${stage.name}` as MessageKey);

  return (
    <section className="animate-fade-in" aria-label={t(`stage.${stage.name}` as MessageKey)}>
      <button
        onClick={() => details && setOpen((v) => !v)}
        className={clsx(
          "group -ml-1 flex max-w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-left text-[14px]",
          details ? "cursor-pointer" : "cursor-default",
        )}
        aria-expanded={details ? open : undefined}
      >
        {stage.interrupted ? <PauseCircle className="h-4 w-4 shrink-0 text-warn" /> : <StageIcon status={stage.status} />}
        <span
          className={clsx(
            "truncate",
            running ? "shimmer-text font-medium" : "text-muted group-hover:text-fg",
            stage.status === "failed" && "text-bad",
            stage.interrupted && "text-warn",
          )}
        >
          {title}
        </span>
        {duration != null && duration > 0 && (
          <span className="shrink-0 text-faint">· {formatDuration(duration, t)}</span>
        )}
        {details && (
          <ChevronRight className={clsx("h-4 w-4 shrink-0 text-faint transition-transform", open && "rotate-90")} />
        )}
      </button>
      {live && <div className="ml-6 mt-1.5">{live}</div>}
      {open && details && <div className="ml-[7px] mt-2 border-l-2 border-line/[0.08] pl-4">{details}</div>}
      {children && <div className="mt-3">{children}</div>}
    </section>
  );
}

function StageIcon({ status }: { status: StageInfo["status"] }) {
  if (status === "running") return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted" />;
  if (status === "failed") return <AlertOctagon className="h-4 w-4 shrink-0 text-bad" />;
  if (status === "done") return <Check className="h-4 w-4 shrink-0 text-faint" />;
  return <Circle className="h-3.5 w-3.5 shrink-0 text-faint" />;
}

/* ---------- Usage detail shown in every stage's expander ---------- */

export function UsageDetail({ detail, stage }: { detail: RunDetail; stage: StageName }) {
  const { t } = useI18n();
  const row = detail.usage?.by_stage?.[stage];
  const info = detail.stages.find((s) => s.name === stage);
  const summary = info?.summary ?? {};
  const entries = Object.entries(summary).filter(
    ([k, v]) => !["queries", "pdf", "evolutions_json", "ledger"].includes(k) && (typeof v === "string" || typeof v === "number" || typeof v === "boolean"),
  );
  return (
    <div className="space-y-2 text-[13px] text-muted">
      {row && row.calls > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <span>{t("run.calls", { n: row.calls })}</span>
          <span>
            in {formatTokens(row.input_tokens)} · out {formatTokens(row.output_tokens)}
          </span>
          {row.cached_input_tokens > 0 && <span>cache {Math.round(row.cache_hit_rate * 100)}%</span>}
          {row.prefix_reuse_rate > 0 && <span>prefix reuse {Math.round(row.prefix_reuse_rate * 100)}%</span>}
        </div>
      )}
      {entries.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          {entries.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-faint">{humanize(k)}</dt>
              <dd className="min-w-0 truncate text-fg">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {info?.running_at && (
        <div className="text-xs text-faint">
          {new Date(info.running_at).toLocaleString()} {info.done_at ? `→ ${new Date(info.done_at).toLocaleTimeString()}` : ""}
        </div>
      )}
    </div>
  );
}

/* ---------- Plan ---------- */

export function PlanContent({ detail, onOpen }: { detail: RunDetail; onOpen: OpenPanel }) {
  const { t, lang } = useI18n();
  const plan = detail.plan;
  if (!plan) return null;
  return (
    <div className="prose-chat">
      <h3 className="!mt-0 !text-[18px]">{plan.working_title}</h3>
      <p>{plan.problem}</p>
      {plan.research_questions.length > 0 && (
        <>
          <h4>{t("plan.questions")}</h4>
          <ol>
            {plan.research_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        </>
      )}
      {plan.hypotheses.length > 0 && (
        <>
          <h4>{t("plan.hypotheses")}</h4>
          <ul className="!list-none !pl-0">
            {plan.hypotheses.map((h, i) => (
              <li key={i} className="!my-2.5 rounded-2xl bg-subtle/[0.035] px-4 py-3 !text-[15px]">
                <div className="font-medium">H{i + 1}. {h.statement}</div>
                <div className="mt-1 text-[14px] leading-6 text-muted">
                  <span className="font-medium text-fg/80">
                    {t("plan.prediction")}
                    {lang === "zh" ? "：" : ": "}
                  </span>
                  {h.prediction}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <h4>
        {t("plan.method")}: {plan.method_name}
      </h4>
      <p>{plan.method_sketch}</p>
      <div className="not-prose mt-3 flex flex-wrap items-center gap-1.5 text-[13px]">
        <span className="mr-1 text-faint">{t("plan.baselines")}</span>
        {plan.baselines.map((b) => (
          <Badge key={b} className="max-w-[320px] truncate" >
            {b.split(":")[0]}
          </Badge>
        ))}
      </div>
      <div className="not-prose mt-2 flex flex-wrap items-center gap-1.5 text-[13px]">
        <span className="mr-1 text-faint">{t("plan.metrics")}</span>
        {plan.metrics.map((m) => (
          <Badge key={m} tone="info" className="max-w-[320px] truncate">
            {m.split(":")[0].replace(/\.$/, "")}
          </Badge>
        ))}
      </div>
      <div className="not-prose mt-4">
        <Button size="sm" variant="outline" icon={<ArrowUpRight className="h-4 w-4" />} onClick={() => onOpen("plan")}>
          {t("panel.plan")}
        </Button>
      </div>
    </div>
  );
}

/* ---------- Survey ---------- */

export function SurveyContent({ stage, onOpen }: { stage: StageInfo; onOpen: OpenPanel }) {
  const { t } = useI18n();
  const s = stage.summary as Record<string, number | string[] | undefined>;
  const stat = (n: unknown, key: MessageKey) =>
    typeof n === "number" ? (
      <span>
        <span className="font-semibold text-fg">{n}</span> {t(key)}
      </span>
    ) : null;
  return (
    <div className="space-y-3">
      <p className="flex flex-wrap gap-x-3 gap-y-1 text-[15px] text-muted">
        {stat(s.retrieved, "survey.retrieved")}
        {stat(s.screened, "survey.screened")}
        {stat(s.kept, "survey.kept")}
        {stat(s.evidence_cards, "survey.cards")}
        {typeof s.source_errors === "number" && s.source_errors > 0 && (
          <span className="text-faint">
            {s.source_errors} {t("survey.sourceErrors")}
          </span>
        )}
      </p>
      <button
        onClick={() => onOpen("sources")}
        className="inline-flex items-center gap-2 rounded-full border border-line/10 py-1 pl-1.5 pr-3 text-[13px] font-medium hover:bg-subtle/[0.04]"
      >
        <span className="flex -space-x-1.5">
          {["a", "S2", "OA"].map((l, i) => (
            <span
              key={l}
              className={clsx(
                "flex h-6 w-6 items-center justify-center rounded-full border-2 border-main text-[9px] font-bold text-white",
                ["bg-[#b31b1b]", "bg-[#1857b6]", "bg-[#d97706]"][i],
              )}
            >
              {l}
            </span>
          ))}
        </span>
        {t("survey.sources")}
        {typeof s.kept === "number" && <span className="text-faint">{s.kept}</span>}
      </button>
    </div>
  );
}

export function SurveyDetails({ stage }: { stage: StageInfo }) {
  const { t } = useI18n();
  const queries = (stage.summary.queries as string[] | undefined) ?? [];
  if (!queries.length) return null;
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-faint">{t("survey.queries")}</div>
      <div className="flex flex-wrap gap-1.5">
        {queries.map((q) => (
          <Badge key={q}>{q}</Badge>
        ))}
      </div>
    </div>
  );
}

/* ---------- Experiments ---------- */

const MODULES = ["experiment_design", "code_implementation", "experiment_execution", "reflection"] as const;

function moduleState(timeline: ExperimentEvent[], module: string, liveModule?: string) {
  const mine = timeline.filter((e) => e.module === module);
  const finishes = mine.filter((e) => e.event === "subagent_finish");
  const last = finishes[finishes.length - 1];
  if (liveModule === module) return { state: "running" as const, rounds: finishes.length, last };
  if (!mine.length) return { state: "pending" as const, rounds: 0, last };
  return { state: last?.outcome === "failed" ? ("failed" as const) : ("done" as const), rounds: finishes.length, last };
}

export function ExperimentsContent({
  runId,
  stage,
  liveEvents,
  onOpen,
}: {
  runId: string;
  stage: ViewStage;
  liveEvents: ExperimentEvent[];
  onOpen: OpenPanel;
}) {
  const { t } = useI18n();
  const running = stage.status === "running" && !stage.interrupted;
  useTicker(running);
  const info = useAsync(() => api.experiments(runId), [runId, stage.status, liveEvents.length], { interval: running ? 15000 : undefined });
  const data = info.data;
  const timeline = useMemo(() => {
    const seen = new Set((data?.timeline ?? []).map((e) => `${e.attempt}|${e.ts}|${e.event}`));
    return [...(data?.timeline ?? []), ...liveEvents.filter((e) => !seen.has(`${e.attempt}|${e.ts}|${e.event}`))];
  }, [data, liveEvents]);
  const liveModule = running ? data?.live?.module : undefined;
  const variants = data?.variants?.length ? data.variants : ((stage.summary.variants as string[] | undefined) ?? []);

  return (
    <div className="space-y-4">
      {data?.synthetic && <Badge tone="warn">{t("run.synthetic")}</Badge>}
      {(timeline.length > 0 || running) && data?.engine !== "fixture" && data?.engine !== "imported" && (
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {MODULES.map((m) => {
            const st = moduleState(timeline, m, liveModule);
            return (
              <li
                key={m}
                className={clsx(
                  "rounded-2xl border px-3 py-2.5 text-[13px] transition-colors",
                  st.state === "running" ? "border-info/40 bg-info/[0.05]" : "border-line/10",
                )}
              >
                <div className="flex items-center gap-1.5">
                  {st.state === "running" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-info" />
                  ) : st.state === "done" ? (
                    <Check className="h-3.5 w-3.5 text-ok" />
                  ) : st.state === "failed" ? (
                    <AlertOctagon className="h-3.5 w-3.5 text-bad" />
                  ) : (
                    <Circle className="h-3 w-3 text-faint" />
                  )}
                  <span className="font-medium">{t(`exp.module.${m}` as MessageKey)}</span>
                </div>
                <div className="mt-1 text-xs text-faint">
                  {st.state === "running" && data?.live
                    ? data.live.model_calls > 0
                      ? t("exp.liveCalls", { n: data.live.model_calls })
                      : t("stage.for", { d: formatDuration(elapsedSince(data.live.since), t) })
                    : st.rounds > 0
                      ? `×${st.rounds}${st.last?.outcome ? ` · ${t(`exp.outcome.${st.last.outcome}` as MessageKey)}` : ""}`
                      : running
                        ? t("stage.waiting")
                        : t("exp.notRun")}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {variants.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
          <span className="mr-1 text-faint">{t("exp.variants")}</span>
          {variants.map((v) => (
            <Badge key={v} tone={v === "proposed" ? "info" : "neutral"}>
              {v}
            </Badge>
          ))}
        </div>
      )}
      <Button size="sm" variant="outline" icon={<FlaskConical className="h-4 w-4" />} onClick={() => onOpen("experiments")}>
        {t("panel.experiments")}
      </Button>
    </div>
  );
}

/* ---------- Analysis ---------- */

export function AnalysisContent({ runId, onOpen }: { runId: string; onOpen: OpenPanel }) {
  const { t } = useI18n();
  const analysis = useAsync(() => api.analysis(runId), [runId]);
  const a = analysis.data;
  if (!a) return null;
  const metrics = a.metrics.slice(0, 3);
  const variants = [a.proposed, ...a.baselines.filter((b) => b !== a.proposed)];
  const best = (metric: string) => {
    const vals = variants.map((v) => a.variants[v]?.[metric]?.value).filter((x): x is number => typeof x === "number");
    return a.lower_is_better[metric] ? Math.min(...vals) : Math.max(...vals);
  };
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-2xl border border-line/10">
        <table className="data-table">
          <thead>
            <tr>
              <th />
              {metrics.map((m) => (
                <th key={m} className="num" title={a.lower_is_better[m] ? t("analysis.lowerBetter") : t("analysis.higherBetter")}>
                  {humanize(m)} {a.lower_is_better[m] ? "↓" : "↑"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {variants.map((v) => (
              <tr key={v}>
                <td className={clsx(v === a.proposed && "font-semibold")}>
                  {v}
                  {v === a.proposed && <span className="ml-1.5 text-xs font-normal text-faint">({t("analysis.proposed")})</span>}
                </td>
                {metrics.map((m) => {
                  const s = a.variants[v]?.[m];
                  const isBest = s && s.value === best(m);
                  return (
                    <td key={m} className="num">
                      <span className={clsx(isBest && "font-semibold")}>{formatMetric(s?.value)}</span>
                      {s?.ci_low != null && s?.ci_high != null && (
                        <span className="ml-1 text-xs text-faint">
                          [{formatMetric(s.ci_low)}, {formatMetric(s.ci_high)}]
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-faint">
        {t("analysis.ci", { c: Math.round(a.confidence * 100) })} · bootstrap · {a.comparisons.length} {t("analysis.comparisons").toLowerCase()}
      </p>
      {a.figure_url && (
        <button onClick={() => onOpen("results")} className="block overflow-hidden rounded-2xl border border-line/10 bg-white">
          <img src={a.figure_url} alt={t("analysis.figure")} className="max-h-[280px] w-auto" loading="lazy" />
        </button>
      )}
    </div>
  );
}

/* ---------- Writing ---------- */

export function WriteContent({ stage, events }: { stage: StageInfo; events: RunEvent[] }) {
  const { t } = useI18n();
  // One-call-per-section writing logs write.section; the author agent logs agent.edit (latest per section).
  const legacy = events.filter((e) => e.kind === "write.section");
  const edits = new Map<string, RunEvent>();
  for (const e of events) if (e.kind === "agent.edit") edits.set(String(e.section), { ...e, kind: "write.section" });
  const sections = legacy.length ? legacy : [...edits.values()];
  const title = stage.summary.title as string | undefined;
  return (
    <div className="space-y-2">
      {title && <div className="text-[16px] font-semibold">{title}</div>}
      <div className="flex flex-wrap gap-1.5">
        {sections.map((e) => (
          <Badge key={e.seq} tone="neutral">
            <Check className="h-3 w-3 text-ok" />
            {humanize(String(e.section))}
            <span className="text-faint">{t("write.words", { n: Number(e.words) })}</span>
          </Badge>
        ))}
      </div>
    </div>
  );
}

/* ---------- Review ---------- */

export function ReviewContent({ detail, events, onOpen }: { detail: RunDetail; events: RunEvent[]; onOpen: OpenPanel }) {
  const { t } = useI18n();
  const rounds = detail.review?.rounds ?? [];
  const latest = [...rounds].reverse().find((r) => r.accepted) ?? rounds[rounds.length - 1];
  const gates = detail.gates;
  const blockers = gates?.findings.filter((f) => f.severity === "blocker").length ?? 0;
  const stop = detail.review?.stop_reason ?? (events.filter((e) => e.kind === "review.stop").pop()?.reason as string | undefined);
  const dims = latest?.dimensions ?? ({} as Record<string, number>);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {gates && (
          <Badge tone={gates.passed ? "ok" : "bad"}>
            {gates.passed ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
            {gates.passed ? t("review.gatesPassed") : t("review.gatesFailed", { n: blockers })}
          </Badge>
        )}
        {latest && (
          <Badge tone="info" className="tabular-nums">
            {t("review.composite")} {latest.composite.toFixed(2)}
          </Badge>
        )}
        {stop && <span className="text-xs text-faint">{t("review.stop", { reason: stop })}</span>}
      </div>
      {rounds.length > 1 && (
        <RoundTrend
          points={rounds.map((r) => ({ round: r.round, value: r.composite, accepted: r.accepted, note: r.accepted ? undefined : t("review.rejected") }))}
          labelRound={(n) => (n === 0 ? t("review.draft") : t("review.round", { n }))}
        />
      )}
      {latest && Object.keys(dims).length > 0 && (
        <div className="max-w-[520px]">
          <ScoreBars rows={Object.entries(dims).map(([k, v]) => ({ label: t(`dim.${k}` as MessageKey), value: v }))} />
        </div>
      )}
      <p className="text-xs leading-5 text-faint">{t("review.compositeHint")}</p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" icon={<ArrowUpRight className="h-4 w-4" />} onClick={() => onOpen("review")}>
          {t("panel.review")}
        </Button>
        <Button size="sm" variant="outline" icon={<ShieldCheck className="h-4 w-4" />} onClick={() => onOpen("claims")}>
          {t("panel.claims")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => onOpen("revisions")}>
          {t("panel.revisions")}
        </Button>
      </div>
    </div>
  );
}

/* ---------- Package: the paper card ---------- */

export function PaperCard({ detail, onOpen }: { detail: RunDetail; onOpen: OpenPanel }) {
  const { t } = useI18n();
  const paper = detail.paper;
  if (!paper) return null;
  return (
    <div className="flex max-w-[560px] items-stretch gap-4 rounded-3xl border border-line/10 p-3 pr-4">
      <button
        onClick={() => onOpen("paper")}
        className="relative w-[112px] shrink-0 overflow-hidden rounded-xl border border-line/10 bg-white"
        aria-label={t("run.openPaper")}
      >
        <img src={paper.thumb_url} alt="" className="h-full w-full object-cover object-top" loading="lazy" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
      </button>
      <div className="flex min-w-0 flex-1 flex-col py-1">
        <div className="flex items-center gap-1.5 text-xs text-faint">
          <FileText className="h-3.5 w-3.5" /> PDF
          {paper.main_pages != null && <span>· {t("package.pages", { n: paper.main_pages })}</span>}
        </div>
        <div className="mt-1 line-clamp-3 text-[15px] font-semibold leading-snug">{paper.title ?? detail.title}</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {paper.unverified ? <Badge tone="bad">{t("run.unverified")}</Badge> : detail.gates?.passed && <Badge tone="ok">{t("review.gatesPassed")}</Badge>}
          {detail.synthetic && <Badge tone="warn">{t("run.synthetic")}</Badge>}
        </div>
        <div className="flex-1" />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="primary" icon={<ExternalLink className="h-4 w-4" />} onClick={() => onOpen("paper")}>
            {t("run.openPaper")}
          </Button>
          <a href={paper.url} download={`${detail.run_id}.pdf`}>
            <Button size="sm" variant="outline" icon={<Download className="h-4 w-4" />}>
              PDF
            </Button>
          </a>
          {detail.status === "done" && (
            <a href={files.bundle(detail.run_id)} download>
              <Button size="sm" variant="ghost">
                .zip
              </Button>
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
