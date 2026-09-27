import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ChevronRight, CircleHelp, Hash, Quote } from "lucide-react";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Claim, ClaimStatus, LineageGraph, RevisionRound } from "../../api/types";
import { formatMetric, humanize, safeUrl } from "../../lib/format";
import { useAsync } from "../../lib/hooks";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { StatusBar } from "../charts";
import { Badge, SectionTitle, Segmented } from "../ui";
import { PanelLoading, PanelMessage, PanelScroll, type TabProps } from "./RightPanel";

export default function TraceTabs({ tab, ...props }: TabProps & { tab: "claims" | "revisions" | "lineage" }) {
  if (tab === "claims") return <ClaimsTab {...props} />;
  if (tab === "revisions") return <RevisionsTab {...props} />;
  return <LineageTab {...props} />;
}

/* ---------- Claim–evidence map ---------- */

const STATUS_ICON: Record<ClaimStatus, ReactNode> = {
  verified: <CheckCircle2 className="h-4 w-4 text-ok" />,
  weak: <AlertTriangle className="h-4 w-4 text-warn" />,
  unverified: <CircleHelp className="h-4 w-4 text-bad" />,
};

function ClaimsTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const map = useAsync(() => api.claims(runId), [runId, detail.updated_at]);
  const [filter, setFilter] = useState<"all" | ClaimStatus>("all");
  const [section, setSection] = useState<string>("all");
  const claims = map.data?.claims ?? [];
  const sections = useMemo(() => [...new Set(claims.map((c) => c.section))], [claims]);
  const rows = claims.filter((c) => (filter === "all" || c.status === filter) && (section === "all" || c.section === section));

  if (map.loading && !map.data) return <PanelLoading />;
  if (!map.data) return <PanelMessage>{map.error?.status === 404 ? t("claims.later") : (map.error?.message ?? t("panel.unavailable"))}</PanelMessage>;
  const s = map.data.stats;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 space-y-3 px-5 pb-3 pt-4">
        <div>
          <div className="text-[15px] font-semibold">{t("claims.title")}</div>
          <p className="mt-0.5 text-xs leading-5 text-faint">{t("claims.subtitle")}</p>
        </div>
        <StatusBar
          parts={[
            { key: "ok", label: t("claims.verified"), value: s.verified },
            { key: "warn", label: t("claims.weak"), value: s.weak },
            { key: "bad", label: t("claims.unverified"), value: s.unverified },
          ]}
        />
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span>
            <Hash className="mr-1 inline h-3 w-3" />
            {t("claims.numbersMatched", { a: s.numbers_matched, b: s.numbers })}
          </span>
          <span>
            <Quote className="mr-1 inline h-3 w-3" />
            {t("claims.citationsCarded", { a: s.citations_carded, b: s.citations })}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: t("claims.all") },
              { value: "verified", label: t("claims.verified") },
              { value: "weak", label: t("claims.weakShort") },
              { value: "unverified", label: t("claims.unverified") },
            ]}
          />
          <select
            value={section}
            onChange={(e) => setSection(e.target.value)}
            className="h-9 rounded-full border border-line/15 bg-main px-3 text-[13px] text-fg outline-none"
            aria-label={t("claims.section")}
          >
            <option value="all">{t("claims.allSections")}</option>
            {sections.map((x) => (
              <option key={x} value={x}>
                {humanize(x)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto border-t border-line/[0.06] px-5 py-3">
        {rows.map((c) => (
          <ClaimRow key={c.id} claim={c} />
        ))}
        {!rows.length && <li className="py-10 text-center text-sm text-faint">{t("panel.empty")}</li>}
      </ul>
    </div>
  );
}

function ClaimRow({ claim }: { claim: Claim }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(claim.status !== "verified");
  return (
    <li className={clsx("rounded-2xl border p-3.5", claim.status === "unverified" ? "border-bad/25" : claim.status === "weak" ? "border-warn/30" : "border-line/10")}>
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-start gap-2.5 text-left" aria-expanded={open}>
        <span className="mt-0.5 shrink-0" aria-label={t(`claims.${claim.status}` as MessageKey)}>
          {STATUS_ICON[claim.status]}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] leading-6">{claim.sentence}</span>
          <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px] text-faint">
            <span>{humanize(claim.section)}</span>·<span>{t(`claims.status.${claim.status}` as MessageKey)}</span>
            {claim.numbers.length > 0 && <Badge className="!h-5">{t("claims.nNumbers", { n: claim.numbers.length })}</Badge>}
            {claim.citations.length > 0 && <Badge className="!h-5">{t("claims.nCitations", { n: claim.citations.length })}</Badge>}
          </span>
        </span>
        <ChevronRight className={clsx("mt-1 h-4 w-4 shrink-0 text-faint transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="ml-[26px] mt-3 space-y-2 animate-fade-in">
          {claim.numbers.map((n, i) => (
            <div key={`n${i}`} className="flex items-start gap-2 text-[12.5px] leading-5">
              {n.match ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" /> : <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" />}
              <span className="min-w-0">
                <code className="rounded bg-subtle/[0.06] px-1 font-mono">{n.text}</code>{" "}
                {n.match ? (
                  <span className="text-muted">
                    {t("claims.matched", { label: n.match.label })} = <span className="tabular-nums">{formatMetric(n.match.value)}</span>
                    <span className="text-faint">
                      {" "}
                      · {n.match.source}
                      {n.match.metrics_file ? ` · ${n.match.metrics_file}` : ""}
                    </span>
                    {n.ambiguous && (
                      <span className="block text-warn" title={(n.alternatives ?? []).join("\n")}>
                        {t("claims.ambiguous", { n: n.alternatives?.length ?? 0 })}
                      </span>
                    )}
                  </span>
                ) : (
                  <span className="text-bad">{t("claims.unmatched")}</span>
                )}
              </span>
            </div>
          ))}
          {claim.citations.map((c) => (
            <div key={c.key} className="text-[12.5px] leading-5">
              <div className="flex items-start gap-2">
                {!c.known ? (
                  <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-bad" />
                ) : c.carded ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" />
                )}
                <span className="min-w-0">
                  <code className="rounded bg-subtle/[0.06] px-1 font-mono">{c.key}</code>{" "}
                  {c.known ? (
                    safeUrl(c.url) ? (
                      <a href={safeUrl(c.url)} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-fg hover:underline">
                        {c.title}
                        {c.year ? ` (${c.year})` : ""}
                      </a>
                    ) : (
                      <span className="text-muted">{c.title}</span>
                    )
                  ) : (
                    <span className="text-bad">{t("claims.unknownKey")}</span>
                  )}
                  {c.known && !c.carded && <span className="text-warn"> · {t("claims.noCard")}</span>}
                </span>
              </div>
              {c.cards.slice(0, 2).map((card, i) => (
                <blockquote key={i} className="ml-[22px] mt-1.5 border-l-2 border-accent/40 pl-2.5 text-[12px] italic text-muted">
                  “{card.quote}”
                </blockquote>
              ))}
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

/* ---------- Revision history ---------- */

function RevisionsTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const revs = useAsync(() => api.revisions(runId), [runId, detail.review?.rounds.length]);
  if (revs.loading && !revs.data) return <PanelLoading />;
  const rounds = revs.data?.rounds ?? [];
  if (!rounds.length) return <PanelMessage>{revs.error?.message ?? t("rev.later")}</PanelMessage>;
  return (
    <PanelScroll>
      <div className="text-[15px] font-semibold">{t("rev.title")}</div>
      <p className="mb-4 mt-0.5 text-xs leading-5 text-faint">{t("rev.subtitle")}</p>
      <ol className="space-y-4">
        {rounds.map((r) => (
          <RevisionCard key={r.round} round={r} />
        ))}
      </ol>
    </PanelScroll>
  );
}

function RevisionCard({ round }: { round: RevisionRound }) {
  const { t } = useI18n();
  const [openSection, setOpenSection] = useState<string | null>(round.sections[0]?.name ?? null);
  return (
    <li className="overflow-hidden rounded-2xl border border-line/10">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <span className="font-medium">{round.round === 0 ? t("review.draft") : t("review.round", { n: round.round })}</span>
        <Badge tone={round.accepted ? "ok" : "neutral"}>{round.accepted ? t("review.accepted") : t("review.rejected")}</Badge>
        {round.composite != null && (
          <span className="text-xs tabular-nums text-muted">
            {round.composite.toFixed(2)}
            {round.delta != null && ` (${round.delta >= 0 ? "+" : ""}${round.delta.toFixed(2)})`}
          </span>
        )}
        {round.note && <span className="text-xs text-faint">{round.note}</span>}
      </div>
      {round.findings.length > 0 && (
        <div className="border-t border-line/[0.06] px-4 py-2.5">
          <div className="mb-1 text-[11.5px] font-medium text-faint">{t("rev.addressed")}</div>
          <ul className="space-y-1 text-[12.5px] leading-5">
            {round.findings.map((f, i) => (
              <li key={f.id ?? i} className="flex gap-1.5">
                <code className="shrink-0 font-mono text-[11px] text-faint">{f.id}</code>
                <span className="text-muted">{f.problem}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {round.sections.length === 0 ? (
        <div className="border-t border-line/[0.06] px-4 py-3 text-xs text-faint">{t("rev.noChanges")}</div>
      ) : (
        <div className="border-t border-line/[0.06]">
          <div className="no-scrollbar flex gap-1 overflow-x-auto px-3 py-2">
            {round.sections.map((s) => (
              <button
                key={s.name}
                onClick={() => setOpenSection(openSection === s.name ? null : s.name)}
                className={clsx(
                  "h-7 shrink-0 rounded-lg px-2.5 text-xs font-medium",
                  openSection === s.name ? "bg-subtle/[0.08] text-fg" : "text-muted hover:bg-subtle/[0.04]",
                )}
              >
                {humanize(s.name)} <span className="font-normal text-faint">{t("rev.words", { a: s.before_words, b: s.after_words })}</span>
              </button>
            ))}
          </div>
          {openSection && <DiffView diff={round.sections.find((s) => s.name === openSection)?.diff ?? ""} />}
        </div>
      )}
    </li>
  );
}

function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n").filter((l) => !l.startsWith("---") && !l.startsWith("+++"));
  return (
    <div className="max-h-[420px] overflow-auto border-t border-line/[0.06] font-mono text-[12px] leading-[1.6]">
      {lines.map((line, i) => (
        <div
          key={i}
          className={clsx(
            "diff-line whitespace-pre-wrap break-words px-4",
            line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" : line.startsWith("@@") ? "diff-hunk" : "text-muted",
          )}
        >
          {line || " "}
        </div>
      ))}
    </div>
  );
}

/* ---------- Lineage ---------- */

function LineageTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const graph = useAsync(() => api.lineage(runId), [runId, detail.updated_at]);
  const env = useAsync(() => api.environment(runId), [runId]);
  const [selected, setSelected] = useState<string | null>(null);
  const [onlyLatest, setOnlyLatest] = useState(true);
  const g = graph.data;
  const upstream = useMemo(() => (g && selected ? upstreamOf(g, selected) : new Set<string>()), [g, selected]);

  if (graph.loading && !g) return <PanelLoading />;
  if (!g || !g.nodes.length) return <PanelMessage>{graph.error?.message ?? t("panel.unavailable")}</PanelMessage>;
  const nodes = g.nodes.filter((n) => !onlyLatest || n.latest || upstream.has(n.id) || n.id === selected);
  const inputsOf = (id: string) => g.edges.filter((e) => e.to === id);

  return (
    <PanelScroll>
      <div className="text-[15px] font-semibold">{t("lineage.title")}</div>
      <p className="mt-0.5 text-xs leading-5 text-faint">{t("lineage.subtitle")}</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <Segmented
          value={onlyLatest ? "latest" : "all"}
          onChange={(v) => setOnlyLatest(v === "latest")}
          options={[
            { value: "latest", label: t("lineage.latest") },
            { value: "all", label: t("lineage.all", { n: g.nodes.length }) },
          ]}
        />
        {selected && (
          <button onClick={() => setSelected(null)} className="text-xs text-muted hover:text-fg">
            {t("lineage.clear")}
          </button>
        )}
      </div>
      {selected && <p className="mt-2 text-xs text-muted">{t("lineage.upstream", { id: selected })}</p>}
      <div className="mt-4 space-y-4">
        {g.stages.map((stage) => {
          const inStage = nodes.filter((n) => n.stage === stage);
          if (!inStage.length) return null;
          return (
            <section key={stage}>
              <div className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-faint">{t(`stage.${stage}` as MessageKey, {}) || stage}</div>
              <div className="flex flex-wrap gap-1.5">
                {inStage.map((n) => {
                  const isSel = n.id === selected;
                  const isUp = upstream.has(n.id);
                  const inputs = inputsOf(n.id);
                  return (
                    <button
                      key={n.id}
                      onClick={() => setSelected(isSel ? null : n.id)}
                      title={`${n.path}\nsha256 ${n.sha256}\n${inputs.map((e) => `${e.kind}: ${e.from}`).join("\n")}`}
                      className={clsx(
                        "flex h-8 items-center gap-1.5 rounded-lg border px-2.5 font-mono text-[11.5px] transition-colors",
                        isSel ? "border-accent bg-accent/10 text-fg" : isUp ? "border-accent/40 bg-accent/[0.05] text-fg" : selected ? "border-line/10 text-faint" : "border-line/10 text-muted hover:border-line/25 hover:text-fg",
                      )}
                    >
                      {n.name}
                      <span className="text-faint">v{n.version}</span>
                      {inputs.length > 0 && <span className="text-[10px] text-faint">←{inputs.length}</span>}
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
      {env.data && Object.keys(env.data).length > 0 && (
        <>
          <SectionTitle>{t("env.title")}</SectionTitle>
          <EnvTable value={env.data} />
        </>
      )}
    </PanelScroll>
  );
}

function upstreamOf(g: LineageGraph, id: string): Set<string> {
  const out = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop()!;
    for (const e of g.edges) {
      if (e.to === cur && !out.has(e.from)) {
        out.add(e.from);
        stack.push(e.from);
      }
    }
  }
  return out;
}

function EnvTable({ value, prefix = "" }: { value: Record<string, unknown>; prefix?: string }) {
  const entries = Object.entries(value);
  return (
    <dl className={clsx("grid grid-cols-[minmax(120px,auto)_1fr] gap-x-4 gap-y-1 text-[12.5px]", !prefix && "rounded-2xl border border-line/10 p-3")}>
      {entries.map(([k, v]) => (
        <Fragment key={k}>
          {v && typeof v === "object" && !Array.isArray(v) ? (
            <>
              <dt className="col-span-2 mt-1.5 font-medium text-fg first:mt-0">{prefix + k}</dt>
              <dd className="col-span-2 pl-3">
                <EnvTable value={v as Record<string, unknown>} prefix={`${prefix}${k}.`} />
              </dd>
            </>
          ) : (
            <>
              <dt className="truncate text-faint">{k}</dt>
              <dd className="min-w-0 break-words font-mono text-[11.5px] text-muted">{Array.isArray(v) ? v.join(", ") : String(v ?? "—")}</dd>
            </>
          )}
        </Fragment>
      ))}
    </dl>
  );
}
