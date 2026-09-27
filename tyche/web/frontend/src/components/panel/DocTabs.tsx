import { Download, FileText } from "lucide-react";
import { useEffect, useRef } from "react";
import { api } from "../../api/client";
import { useAsync } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { Markdown } from "../Markdown";
import { Badge, Button, EmptyState, SectionTitle } from "../ui";
import { PanelLoading, PanelMessage, PanelScroll, type TabProps } from "./RightPanel";

export default function DocTabs({ tab, ...props }: TabProps & { tab: "paper" | "plan" | "report" | "log" }) {
  if (tab === "paper") return <PaperTab {...props} />;
  if (tab === "plan") return <PlanTab {...props} />;
  if (tab === "report") return <ReportTab {...props} />;
  return <LogTab {...props} />;
}

function PaperTab({ detail }: TabProps) {
  const { t } = useI18n();
  const paper = detail.paper;
  if (!paper) {
    return <EmptyState icon={<FileText />} title={t("panel.unavailable")} body={t("panel.paperLater")} />;
  }
  return (
    <div className="flex h-full flex-col bg-[#525659] dark:bg-[#2a2a2a]">
      {paper.unverified && (
        <div className="shrink-0 bg-bad px-4 py-1.5 text-center text-xs font-medium text-white">{t("run.unverified")}</div>
      )}
      <iframe key={paper.url} title={paper.title ?? "paper"} src={`${paper.url}#view=FitH&toolbar=1`} className="min-h-0 w-full flex-1 border-0" />
      <div className="flex shrink-0 items-center justify-between gap-2 border-t border-line/[0.06] bg-main px-4 py-2 text-xs text-faint">
        <span className="truncate">
          {paper.source === "package" ? "package/" : "review/"}
          {paper.unverified ? "paper_UNVERIFIED.pdf" : "paper.pdf"}
          {paper.main_pages != null && ` · ${t("package.pages", { n: paper.main_pages })}`}
        </span>
        <a href={paper.url} download={`${detail.run_id}.pdf`}>
          <Button size="sm" variant="ghost" icon={<Download className="h-4 w-4" />}>
            PDF
          </Button>
        </a>
      </div>
    </div>
  );
}

function PlanTab({ detail }: TabProps) {
  const { t } = useI18n();
  const plan = detail.plan;
  if (!plan) return <PanelMessage>{t("panel.unavailable")}</PanelMessage>;
  const list = (items: string[]) => (
    <ul className="list-disc space-y-1 pl-5 text-[14px] leading-6">
      {items.map((x) => (
        <li key={x}>{x}</li>
      ))}
    </ul>
  );
  return (
    <PanelScroll>
      <h2 className="text-[20px] font-semibold leading-snug">{plan.working_title}</h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge tone="info">{plan.experiment_family}</Badge>
        {plan.keywords.map((k) => (
          <Badge key={k}>{k}</Badge>
        ))}
      </div>
      <SectionTitle>{t("plan.problem")}</SectionTitle>
      <p className="text-[14px] leading-6">{plan.problem}</p>
      <SectionTitle>{t("plan.motivation")}</SectionTitle>
      <p className="text-[14px] leading-6">{plan.motivation}</p>
      <SectionTitle>{t("plan.questions")}</SectionTitle>
      <ol className="list-decimal space-y-1 pl-5 text-[14px] leading-6">
        {plan.research_questions.map((q) => (
          <li key={q}>{q}</li>
        ))}
      </ol>
      <SectionTitle>{t("plan.hypotheses")}</SectionTitle>
      <div className="space-y-2">
        {plan.hypotheses.map((h, i) => (
          <div key={i} className="rounded-2xl border border-line/10 p-3 text-[14px] leading-6">
            <div className="font-medium">
              H{i + 1}. {h.statement}
            </div>
            <div className="mt-1 text-muted">
              {t("plan.prediction")}: {h.prediction}
            </div>
          </div>
        ))}
      </div>
      <SectionTitle>
        {t("plan.method")} · {plan.method_name}
      </SectionTitle>
      <Markdown text={plan.method_sketch} compact />
      <SectionTitle>{t("plan.task")}</SectionTitle>
      <p className="text-[14px] leading-6">{plan.task_description}</p>
      <SectionTitle>{t("plan.baselines")}</SectionTitle>
      {list(plan.baselines)}
      <SectionTitle>{t("plan.metrics")}</SectionTitle>
      {list(plan.metrics)}
      <SectionTitle>{t("plan.contributions")}</SectionTitle>
      {list(plan.contributions)}
      <SectionTitle>{t("plan.limits")}</SectionTitle>
      {list(plan.scope_limits)}
      <SectionTitle>{t("survey.queries")}</SectionTitle>
      <div className="flex flex-wrap gap-1.5">
        {plan.search_queries.map((q) => (
          <Badge key={q}>{q}</Badge>
        ))}
      </div>
      {detail.notes && (
        <>
          <SectionTitle>{t("run.notes")}</SectionTitle>
          <div className="rounded-2xl bg-subtle/[0.035] p-4">
            <Markdown text={detail.notes} compact />
          </div>
        </>
      )}
    </PanelScroll>
  );
}

function ReportTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const report = useAsync(() => api.report(runId), [runId, detail.updated_at]);
  if (report.loading && !report.data) return <PanelLoading />;
  if (!report.data) return <PanelMessage>{t("panel.reportLater")}</PanelMessage>;
  return (
    <PanelScroll>
      <Markdown text={report.data} />
    </PanelScroll>
  );
}

function LogTab({ runId, detail }: TabProps) {
  const { t } = useI18n();
  const running = detail.status === "running";
  const log = useAsync(() => api.log(runId, 800), [runId], { interval: running ? 3000 : undefined });
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const lines = log.data?.lines ?? [];
  useEffect(() => {
    if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines.length]);
  if (log.loading && !log.data) return <PanelLoading />;
  if (!lines.length) return <PanelMessage>{t("panel.logEmpty")}</PanelMessage>;
  return (
    <div className="flex h-full flex-col">
      <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="min-h-0 flex-1 overflow-auto bg-sidebar px-4 py-3 font-mono text-[12px] leading-[1.6] text-fg/90"
      >
        {lines.map((line, i) => (
          <div key={i} className={line.includes("Error") || line.includes("Traceback") ? "text-bad" : line.startsWith("[tyche]") ? "text-fg" : "text-muted"}>
            {line || " "}
          </div>
        ))}
      </div>
      {log.data?.path && <div className="shrink-0 truncate border-t border-line/[0.06] px-4 py-1.5 font-mono text-[11px] text-faint">{log.data.path}</div>}
    </div>
  );
}
