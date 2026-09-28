import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleDot, Equal, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Dimension, LedgerEntry } from "../../api/types";
import { formatMetric, formatP, humanize } from "../../lib/format";
import { useAsync } from "../../lib/hooks";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { RoundTrend, ScoreBars } from "../charts";
import { Badge, SectionTitle, Segmented } from "../ui";
import { PanelLoading, PanelMessage, PanelScroll, type TabProps } from "./RightPanel";

export default function ResultsReviewTabs({ tab, ...props }: TabProps & { tab: "results" | "review" }) {
  return tab === "results" ? <ResultsTab {...props} /> : <ReviewTab {...props} />;
}

function ResultsTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const status = detail.stages.find((s) => s.name === "analysis")?.status;
  const analysis = useAsync(() => api.analysis(runId), [runId, status], { enabled: status === "done" });
  if (status !== "done") return <PanelMessage>{t("panel.unavailable")}</PanelMessage>;
  if (analysis.loading && !analysis.data) return <PanelLoading />;
  const a = analysis.data;
  if (!a) return <PanelMessage>{analysis.error?.message ?? t("panel.unavailable")}</PanelMessage>;
  const variants = [a.proposed, ...a.baselines.filter((b) => b !== a.proposed)];
  return (
    <PanelScroll>
      <p className="text-xs leading-5 text-faint">{t("results.note", { c: Math.round(a.confidence * 100) })}</p>
      <SectionTitle>{t("analysis.results")}</SectionTitle>
      <div className="overflow-x-auto rounded-2xl border border-line/10">
        <table className="data-table">
          <thead>
            <tr>
              <th />
              {a.metrics.map((m) => (
                <th key={m} className="num">
                  {humanize(m)} {a.lower_is_better[m] ? "↓" : "↑"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {variants.map((v) => (
              <tr key={v}>
                <td className={clsx(v === a.proposed && "font-semibold")}>{v}</td>
                {a.metrics.map((m) => {
                  const s = a.variants[v]?.[m];
                  return (
                    <td key={m} className="num" title={s?.n ? `n=${s.n}` : undefined}>
                      {formatMetric(s?.value)}
                      {s?.ci_low != null && s.ci_high != null && (
                        <div className="text-[11px] text-faint">
                          [{formatMetric(s.ci_low)}, {formatMetric(s.ci_high)}]
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {a.comparisons.length > 0 && (
        <>
          <SectionTitle>{t("analysis.comparisons")}</SectionTitle>
          <div className="overflow-x-auto rounded-2xl border border-line/10">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("results.metric")}</th>
                  <th>{t("results.vs")}</th>
                  <th className="num">{t("analysis.diff")}</th>
                  <th className="num">{t("analysis.ci", { c: Math.round(a.confidence * 100) })}</th>
                  <th className="num">{t("analysis.p")}</th>
                  <th className="num">n</th>
                </tr>
              </thead>
              <tbody>
                {a.comparisons.map((c, i) => (
                  <tr key={i}>
                    <td>{humanize(c.metric)}</td>
                    <td className="text-muted">{c.baseline}</td>
                    <td className="num">
                      <span className="inline-flex items-center gap-1">
                        {c.diff === 0 && c.ci_low === 0 && c.ci_high === 0 ? (
                          <Equal className="h-3.5 w-3.5 text-faint" aria-label={t("results.tie")} />
                        ) : c.better ? (
                          <CheckCircle2 className="h-3.5 w-3.5 text-ok" aria-label={t("results.better")} />
                        ) : (
                          <CircleDot className="h-3.5 w-3.5 text-faint" aria-label={t("results.notBetter")} />
                        )}
                        {c.diff >= 0 ? "+" : ""}
                        {formatMetric(c.diff)}
                      </span>
                    </td>
                    <td className="num text-muted">
                      {c.ci_low != null && c.ci_high != null ? `[${formatMetric(c.ci_low)}, ${formatMetric(c.ci_high)}]` : "—"}
                    </td>
                    <td className="num">{formatP(c.p_value)}</td>
                    <td className="num text-muted">{c.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {a.figure_url && (
        <>
          <SectionTitle>{t("analysis.figure")}</SectionTitle>
          <div className="overflow-hidden rounded-2xl border border-line/10 bg-white p-2">
            <img src={a.figure_url} alt={t("analysis.figure")} className="mx-auto w-full" />
          </div>
        </>
      )}
    </PanelScroll>
  );
}

type ReviewView = "overview" | "reviewers" | "ledger" | "gates";

function ReviewTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const [view, setView] = useState<ReviewView>("overview");
  const review = detail.review;
  const status = detail.stages.find((s) => s.name === "review")?.status;
  const ledger = useAsync(() => api.ledger(runId), [runId, status, review?.rounds.length], { enabled: view === "ledger" });
  if (!review && !detail.gates) return <PanelMessage>{t("panel.unavailable")}</PanelMessage>;
  const rounds = review?.rounds ?? [];
  const latest = [...rounds].reverse().find((r) => r.accepted) ?? rounds[rounds.length - 1];

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 px-5 pb-3 pt-4">
        <Segmented<ReviewView>
          value={view}
          onChange={setView}
          options={[
            { value: "overview", label: t("review.overview") },
            { value: "reviewers", label: t("review.reviewers") },
            { value: "ledger", label: t("review.findingsShort") },
            { value: "gates", label: t("review.gates") },
          ]}
        />
      </div>
      <div className="min-h-0 flex-1 border-t border-line/[0.06]">
        {view === "overview" && (
          <PanelScroll>
            {latest && (
              <div className="flex items-baseline gap-3">
                <span className="text-[34px] font-semibold tabular-nums leading-none">{latest.composite.toFixed(2)}</span>
                <span className="text-sm text-muted">{t("review.composite")} · /10</span>
              </div>
            )}
            <p className="mt-2 text-xs leading-5 text-faint">{t("review.compositeHint")}</p>
            {rounds.length > 0 && (
              <>
                <SectionTitle>{t("review.rounds")}</SectionTitle>
                <RoundTrend
                  points={rounds.map((r) => ({ round: r.round, value: r.composite, accepted: r.accepted, note: r.accepted ? t("review.accepted") : t("review.rejected") }))}
                  labelRound={(n) => (n === 0 ? t("review.draft") : `R${n}`)}
                />
                <div className="mt-3 overflow-x-auto rounded-2xl border border-line/10">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>{t("review.roundCol")}</th>
                        <th className="num">{t("review.composite")}</th>
                        <th className="num">Δ</th>
                        <th>{t("review.decision")}</th>
                        <th className="num">{t("review.blockersCol")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rounds.map((r) => (
                        <tr key={r.round}>
                          <td>{r.round === 0 ? t("review.draft") : t("review.round", { n: r.round })}</td>
                          <td className="num">{r.composite.toFixed(2)}</td>
                          <td className="num text-muted">{r.delta != null ? `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(2)}` : "—"}</td>
                          <td>
                            <span className={clsx("inline-flex items-center gap-1", r.accepted ? "text-ok" : "text-muted")}>
                              {r.accepted ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                              {r.accepted ? t("review.accepted") : t("review.rejected")}
                            </span>
                          </td>
                          <td className="num">{r.blockers}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {latest && (
              <>
                <SectionTitle>{t("review.dimensions")}</SectionTitle>
                <ScoreBars rows={Object.entries(latest.dimensions).map(([k, v]) => ({ label: t(`dim.${k}` as MessageKey), value: v }))} />
              </>
            )}
            {review?.stop_reason && <p className="mt-5 text-xs text-faint">{t("review.stop", { reason: review.stop_reason })}</p>}
          </PanelScroll>
        )}
        {view === "reviewers" && <Reviewers reviews={review?.reviews ?? {}} />}
        {view === "ledger" && (ledger.loading && !ledger.data ? <PanelLoading /> : <Ledger entries={ledger.data?.entries ?? []} />)}
        {view === "gates" && <GatesView gates={detail.gates} />}
      </div>
    </div>
  );
}

function Reviewers({ reviews }: { reviews: NonNullable<TabProps["detail"]["review"]>["reviews"] }) {
  const { t } = useI18n();
  const names = Object.keys(reviews);
  if (!names.length) return <PanelMessage>{t("panel.empty")}</PanelMessage>;
  return (
    <PanelScroll className="space-y-5">
      {names.map((name) => {
        const r = reviews[name];
        return (
          <section key={name} className="rounded-2xl border border-line/10 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="font-medium">{humanize(name)}</div>
              <Badge tone="info" className="tabular-nums">
                {t("review.overall")} {r.overall.toFixed(1)} · {t("review.confidence")} {r.confidence}
              </Badge>
            </div>
            {r.summary && <p className="mt-2 text-[13.5px] leading-6 text-muted">{r.summary}</p>}
            <div className="mt-3">
              <ScoreBars rows={(Object.entries(r.scores) as [Dimension, number][]).map(([k, v]) => ({ label: t(`dim.${k}` as MessageKey), value: v }))} />
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <List title={t("review.strengths")} items={r.strengths} />
              <List title={t("review.weaknesses")} items={r.weaknesses} />
            </div>
          </section>
        );
      })}
    </PanelScroll>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold text-fg">{title}</div>
      <ul className="list-disc space-y-1 pl-4 text-[13px] leading-5 text-muted">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

const SEVERITY_ORDER = { blocker: 0, major: 1, minor: 2 } as const;

function Ledger({ entries }: { entries: LedgerEntry[] }) {
  const { t } = useI18n();
  const [status, setStatus] = useState<"all" | "open" | "resolved">("all");
  const rows = useMemo(
    () =>
      entries
        .filter((e) => status === "all" || (status === "open" ? e.status === "open" || e.status === "unaddressed" : e.status === "resolved"))
        .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]),
    [entries, status],
  );
  if (!entries.length) return <PanelMessage>{t("panel.empty")}</PanelMessage>;
  return (
    <PanelScroll>
      <div className="mb-3 flex items-center justify-between gap-2">
        <Segmented
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: `${t("claims.all")} ${entries.length}` },
            { value: "open", label: `${t("ledger.open")} ${entries.filter((e) => e.status === "open" || e.status === "unaddressed").length}` },
            { value: "resolved", label: `${t("ledger.resolved")} ${entries.filter((e) => e.status === "resolved").length}` },
          ]}
        />
      </div>
      <ul className="space-y-2.5">
        {rows.map((e) => (
          <li key={e.id} className="rounded-2xl border border-line/10 p-3.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={e.severity === "blocker" ? "bad" : e.severity === "major" ? "warn" : "neutral"}>
                {e.severity === "blocker" ? <ShieldAlert className="h-3 w-3" /> : e.severity === "major" ? <AlertTriangle className="h-3 w-3" /> : null}
                {t(`severity.${e.severity}` as MessageKey)}
              </Badge>
              <Badge tone={e.status === "resolved" ? "ok" : "neutral"}>
                {e.status === "resolved" && <CheckCircle2 className="h-3 w-3" />}
                {t(`ledger.${e.status}` as MessageKey)}
              </Badge>
              <span className="text-xs text-faint">
                {humanize(e.section)} · {e.dimension ? t(`dim.${e.dimension}` as MessageKey) : e.source} · R{e.round_opened}
              </span>
              <code className="ml-auto font-mono text-[11px] text-faint">{e.id}</code>
            </div>
            <p className="mt-2 text-[13.5px] leading-6">{e.problem}</p>
            {e.quote && <blockquote className="mt-1.5 border-l-2 border-line/15 pl-3 text-[12.5px] italic leading-5 text-muted">{e.quote}</blockquote>}
            {e.fix && (
              <p className="mt-2 text-[12.5px] leading-5 text-muted">
                <span className="font-medium text-fg">{t("ledger.fix")}:</span> {e.fix}
              </p>
            )}
            {e.response && (
              <p className="mt-1 text-[12.5px] leading-5 text-muted">
                <span className="font-medium text-fg">{t("ledger.response")}:</span> {e.response}
              </p>
            )}
          </li>
        ))}
      </ul>
    </PanelScroll>
  );
}

function GatesView({ gates }: { gates: TabProps["detail"]["gates"] }) {
  const { t } = useI18n();
  if (!gates) return <PanelMessage>{t("panel.unavailable")}</PanelMessage>;
  const stats = Object.entries(gates.stats).filter(([, v]) => typeof v === "number" || typeof v === "boolean" || typeof v === "string");
  return (
    <PanelScroll>
      <div className={clsx("flex items-center gap-2 rounded-2xl p-4", gates.passed ? "bg-ok/[0.07]" : "bg-bad/[0.07]")}>
        {gates.passed ? <ShieldCheck className="h-5 w-5 text-ok" /> : <ShieldAlert className="h-5 w-5 text-bad" />}
        <span className="font-medium">{gates.passed ? t("review.gatesPassed") : t("review.gatesFailed", { n: gates.findings.filter((f) => f.severity === "blocker").length })}</span>
      </div>
      <p className="mt-2 text-xs leading-5 text-faint">{t("gates.note")}</p>
      {stats.length > 0 && (
        <dl className="mt-4 grid grid-cols-2 gap-2">
          {stats.map(([k, v]) => (
            <div key={k} className="rounded-xl bg-subtle/[0.035] px-3 py-2">
              <dt className="text-[11.5px] text-faint">{humanize(k)}</dt>
              <dd className="text-sm font-medium tabular-nums">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {gates.findings.length > 0 && (
        <>
          <SectionTitle>{t("gates.findings")}</SectionTitle>
          <ul className="space-y-2">
            {gates.findings.map((f, i) => (
              <li key={i} className="rounded-xl border border-line/10 p-3 text-[13px]">
                <div className="flex items-center gap-1.5">
                  <Badge tone={f.severity === "blocker" ? "bad" : f.severity === "major" ? "warn" : "neutral"}>{t(`severity.${f.severity}` as MessageKey)}</Badge>
                  <span className="font-mono text-[11.5px] text-faint">
                    {f.gate} · {f.section}
                  </span>
                </div>
                <p className="mt-1.5 leading-5">{f.message}</p>
                {f.context && <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap rounded-lg bg-subtle/[0.04] p-2 font-mono text-[11.5px] text-muted">{f.context}</pre>}
              </li>
            ))}
          </ul>
        </>
      )}
    </PanelScroll>
  );
}
