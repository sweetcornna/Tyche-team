import clsx from "clsx";
import {
  AlertOctagon,
  Archive,
  ArrowDown,
  ArrowUp,
  Check,
  Copy,
  Download,
  FileText,
  History,
  MoreHorizontal,
  PanelRight,
  PauseCircle,
  Pencil,
  Pin,
  PinOff,
  Play,
  RotateCcw,
  Square,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, files, type ResumeRequest } from "../api/client";
import type { AgentTranscript, OperatorMessage, RunDetail, RunEvent, StageInfo, StageName } from "../api/types";
import { DIRECTION_ICONS, useAutoGrow } from "../components/Composer";
import { Header, effortLabel } from "../components/Header";
import { Markdown } from "../components/Markdown";
import { RightPanel, PANEL_TABS, type PanelTab } from "../components/panel/RightPanel";
import { AgentStatus, AgentWork, FEED_SESSION, FeedView, useAgentTranscript } from "../components/run/AgentFeed";
import {
  AnalysisContent,
  ExperimentsContent,
  PaperCard,
  PlanContent,
  ReviewContent,
  StageBlock,
  SurveyContent,
  SurveyDetails,
  UsageDetail,
  WriteContent,
  type ViewStage,
} from "../components/run/StageBlocks";
import { useRun } from "../components/run/useRun";
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  IconButton,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
  Skeleton,
  Switch,
  TextField,
  Tooltip,
} from "../components/ui";
import { STAGES, elapsedSince, formatDuration, relativeTime } from "../lib/format";
import { copyText, isMac, useMediaQuery, useTicker } from "../lib/hooks";
import { useI18n, type MessageKey } from "../lib/i18n";
import { usePersistent } from "../lib/prefs";
import { routePath, useRouter } from "../lib/router";
import { useStore } from "../lib/store";
import { useToast } from "../lib/toast";

type Phase =
  | { kind: "running"; stage: StageInfo | undefined }
  | { kind: "plan-review" }
  | { kind: "paused"; after: StageName | undefined }
  | { kind: "failed"; stage: StageInfo }
  | { kind: "stopped"; stage: StageInfo | undefined }
  | { kind: "done" }
  | { kind: "pending" };

function phaseOf(detail: RunDetail): Phase {
  const running = detail.stages.find((s) => s.status === "running");
  const failed = detail.stages.find((s) => s.status === "failed");
  const lastDone = [...detail.stages].reverse().find((s) => s.status === "done");
  if (detail.status === "running") return { kind: "running", stage: running };
  if (failed && detail.status === "failed") return { kind: "failed", stage: failed };
  if (detail.status === "stopped") return { kind: "stopped", stage: running };
  if (detail.status === "done") return { kind: "done" };
  if (detail.status === "paused") return lastDone?.name === "plan" ? { kind: "plan-review" } : { kind: "paused", after: lastDone?.name };
  return { kind: "pending" };
}

export function RunView({ id, tab }: { id: string; tab?: string }) {
  const { t } = useI18n();
  const { navigate } = useRouter();
  const { detail, error, events, experimentEvents, connected, reload } = useRun(id);
  const mobile = useMediaQuery("(max-width: 1023px)");
  const [lastTab, setLastTab] = usePersistent<PanelTab>("tyche.lastPanel", "plan");
  const panelTab = PANEL_TABS.includes(tab as PanelTab) ? (tab as PanelTab) : undefined;

  const openPanel = useCallback(
    (next: string) => {
      setLastTab(next as PanelTab);
      navigate(routePath({ name: "run", id, tab: next }), { replace: !!panelTab });
    },
    [id, navigate, panelTab, setLastTab],
  );
  const closePanel = useCallback(() => navigate(routePath({ name: "run", id }), { replace: true }), [id, navigate]);

  useEffect(() => {
    if (detail?.title) document.title = `${detail.title} · Tyche`;
    return () => {
      document.title = "Tyche";
    };
  }, [detail?.title]);

  // ⌘. toggles the side panel (bound in App via a custom event).
  useEffect(() => {
    const onToggle = () => (panelTab ? closePanel() : openPanel(lastTab));
    window.addEventListener("tyche:toggle-panel", onToggle);
    return () => window.removeEventListener("tyche:toggle-panel", onToggle);
  }, [panelTab, closePanel, openPanel, lastTab]);

  if (error && !detail) {
    return (
      <div className="flex h-full flex-col">
        <Header />
        <EmptyState
          icon={<AlertOctagon />}
          title={error.status === 404 ? t("run.notFound") : t("common.error")}
          body={error.status === 404 ? undefined : error.message}
          action={
            <Button variant="outline" onClick={() => (error.status === 404 ? navigate("/") : reload())}>
              {error.status === 404 ? t("nav.new") : t("common.retry")}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-w-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <RunHeader detail={detail} connected={connected} panelOpen={!!panelTab} onTogglePanel={() => (panelTab ? closePanel() : openPanel(detail?.paper ? "paper" : lastTab))} onOpen={openPanel} />
        {detail ? (
          <Conversation detail={detail} events={events} experimentEvents={experimentEvents} onOpen={openPanel} reload={reload} />
        ) : (
          <ConversationSkeleton />
        )}
      </div>
      {panelTab && detail && (
        <RightPanel
          runId={id}
          detail={detail}
          tab={panelTab}
          onTab={openPanel}
          onClose={closePanel}
          events={events}
          experimentEvents={experimentEvents}
          overlay={mobile}
        />
      )}
    </div>
  );
}

/* ---------- Header ---------- */

function RunHeader({
  detail,
  connected,
  panelOpen,
  onTogglePanel,
  onOpen,
}: {
  detail: RunDetail | undefined;
  connected: boolean;
  panelOpen: boolean;
  onTogglePanel: () => void;
  onOpen: (tab: string) => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const { navigate } = useRouter();
  const { upsertRun, confirm, refreshRuns } = useStore();
  const [renaming, setRenaming] = useState(false);
  const roles = detail?.config?.roles ?? {};
  const role = roles.writer ?? roles.default ?? Object.values(roles)[0];
  const effort = (role?.extra_body?.reasoning_effort as string | undefined) ?? null;
  const running = detail?.status === "running";

  const patch = async (body: { pinned?: boolean; archived?: boolean; title?: string }) => {
    if (!detail) return;
    try {
      const updated = await api.patch(detail.run_id, body);
      upsertRun(updated);
      if (body.archived) {
        toast("success", t("toast.archived"));
        navigate("/");
      }
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    }
  };

  const remove = async () => {
    if (!detail) return;
    const ok = await confirm({ title: t("run.deleteConfirm"), body: t("run.deleteBody"), confirmLabel: t("run.delete"), destructive: true });
    if (!ok) return;
    try {
      await api.remove(detail.run_id);
      toast("success", t("toast.deleted"));
      await refreshRuns();
      navigate("/");
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    }
  };

  return (
    <>
      <Header
        left={
          <div className="flex min-w-0 items-center gap-2 pl-1">
            <span className="truncate text-[17px] font-medium tracking-[-0.01em]" title={role?.model_name}>
              {role?.model_name ?? "Tyche"}
              {effort && <span className="ml-1.5 text-muted">{effortLabel(effort, t)}</span>}
            </span>
            {running && (
              <Tooltip content={connected ? t("run.live") : t("run.reconnecting")}>
                <span
                  className={clsx(
                    "inline-flex h-6 items-center gap-1.5 rounded-full px-2 text-xs font-medium",
                    connected ? "bg-ok/10 text-ok" : "bg-warn/12 text-warn",
                  )}
                >
                  <span className={clsx("h-1.5 w-1.5 rounded-full", connected ? "animate-pulse-soft bg-ok" : "bg-warn")} />
                  {connected ? t("run.live") : t("run.reconnecting")}
                </span>
              </Tooltip>
            )}
          </div>
        }
        right={
          detail && (
            <>
              {detail.paper && (
                <Button size="sm" variant="outline" className="hidden sm:inline-flex" icon={<FileText className="h-4 w-4" />} onClick={() => onOpen("paper")}>
                  {t("panel.paper")}
                </Button>
              )}
              <IconButton label={t("run.viewIn")} shortcut={`${isMac ? "⌘" : "Ctrl+"}.`} active={panelOpen} onClick={onTogglePanel}>
                <PanelRight className="h-5 w-5" />
              </IconButton>
              <MenuRoot>
                <MenuTrigger asChild>
                  <IconButton label={t("run.more")} tooltip={false}>
                    <MoreHorizontal className="h-5 w-5" />
                  </IconButton>
                </MenuTrigger>
                <MenuContent align="end" className="w-[240px]">
                  <MenuItem icon={<Pencil />} onSelect={() => setRenaming(true)}>
                    {t("run.rename")}
                  </MenuItem>
                  <MenuItem icon={detail.pinned ? <PinOff /> : <Pin />} onSelect={() => patch({ pinned: !detail.pinned })}>
                    {detail.pinned ? t("run.unpin") : t("run.pin")}
                  </MenuItem>
                  <MenuItem
                    icon={<Copy />}
                    onSelect={async () => {
                      await copyText(detail.run_id);
                      toast("success", t("toast.copied"), detail.run_id);
                    }}
                  >
                    {t("run.copyId")}
                  </MenuItem>
                  {detail.paper && (
                    <>
                      <MenuSeparator />
                      <MenuLabel>{t("run.download")}</MenuLabel>
                      <MenuItem icon={<Download />} onSelect={() => download(detail.paper!.url, `${detail.run_id}.pdf`)}>
                        {detail.paper.unverified ? "paper_UNVERIFIED.pdf" : "paper.pdf"}
                      </MenuItem>
                      {detail.status === "done" && (
                        <MenuItem icon={<Download />} onSelect={() => download(files.bundle(detail.run_id), `${detail.run_id}.zip`)}>
                          {t("run.downloadBundle")}
                        </MenuItem>
                      )}
                    </>
                  )}
                  <MenuSeparator />
                  <MenuItem icon={<Archive />} onSelect={() => patch({ archived: true })}>
                    {t("run.archive")}
                  </MenuItem>
                  <MenuItem icon={<Trash2 />} danger disabled={running} onSelect={remove}>
                    {t("run.delete")}
                  </MenuItem>
                </MenuContent>
              </MenuRoot>
            </>
          )
        }
      />
      {detail && <RenameDialog open={renaming} onOpenChange={setRenaming} value={detail.title} onSave={(title) => patch({ title })} />}
    </>
  );
}

function download(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function RenameDialog({ open, onOpenChange, value, onSave }: { open: boolean; onOpenChange: (v: boolean) => void; value: string; onSave: (v: string) => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    if (open) setDraft(value);
  }, [open, value]);
  const submit = () => {
    const title = draft.trim();
    if (title && title !== value) onSave(title);
    onOpenChange(false);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("run.rename")}>
      <div className="px-6 pb-6 pt-2">
        <TextField autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} maxLength={200} />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={submit}>
            {t("common.save")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/* ---------- Conversation ---------- */

function ConversationSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[768px] space-y-6 px-4 pt-8 md:px-6">
      <div className="flex justify-end">
        <Skeleton className="h-11 w-[60%] rounded-3xl" />
      </div>
      <Skeleton className="h-5 w-48" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-5 w-40" />
    </div>
  );
}

function Conversation({
  detail,
  events,
  experimentEvents,
  onOpen,
  reload,
}: {
  detail: RunDetail;
  events: RunEvent[];
  experimentEvents: Parameters<typeof ExperimentsContent>[0]["liveEvents"];
  onOpen: (tab: string) => void;
  reload: () => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const phase = phaseOf(detail);
  // The agent session the running stage shows (planner or author), shared by its feed and the status line.
  const liveStage = phase.kind === "running" && phase.stage && FEED_SESSION[phase.stage.name] ? phase.stage.name : undefined;
  const feedSession = liveStage ? FEED_SESSION[liveStage] : undefined;
  const liveTranscript = useAgentTranscript(detail.run_id, liveStage, feedSession, { live: !!liveStage, events });
  const visible: ViewStage[] = detail.stages
    .filter((s) => s.status !== "pending")
    .map((s) => (phase.kind === "stopped" && s.status === "running" ? { ...s, interrupted: true } : s));

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  };
  const toBottom = (smooth = true) => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: smooth ? "smooth" : "auto" });

  // Follow new content while the reader is at the bottom (like a streaming reply).
  const contentKey = `${visible.map((s) => s.status).join()}|${events.length}|${phase.kind}|${liveTranscript?.items.length ?? 0}`;
  useLayoutEffect(() => {
    if (atBottom) toBottom(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contentKey]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[768px] px-4 pb-16 pt-4 md:px-6">
          <UserTurn detail={detail} />
          <div className="mt-8 space-y-7">
            {visible.map((stage) => (
              <StageTurn
                key={stage.name}
                stage={stage}
                detail={detail}
                events={events}
                experimentEvents={experimentEvents}
                onOpen={onOpen}
                liveTranscript={stage.name === liveStage ? liveTranscript : null}
              />
            ))}
            <PhaseCard phase={phase} detail={detail} reload={reload} onOpen={onOpen} />
          </div>
        </div>
      </div>
      {!atBottom && (
        <button
          onClick={() => toBottom()}
          aria-label="Scroll to bottom"
          className="absolute bottom-[112px] left-1/2 z-10 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-line/10 bg-main text-fg shadow-card transition-opacity hover:bg-sidebar"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      )}
      <ControlDock detail={detail} phase={phase} reload={reload} events={events} feedSession={feedSession} liveTranscript={liveTranscript} />
    </div>
  );
}

function UserTurn({ detail }: { detail: RunDetail }) {
  const { t, lang } = useI18n();
  const { meta } = useStore();
  const [notesOpen, setNotesOpen] = useState(false);
  const direction = meta?.directions.find((d) => d.name === detail.direction);
  return (
    <div className="group flex flex-col items-end gap-2">
      <div className="flex flex-wrap justify-end gap-2">
        <span className="inline-flex h-9 items-center gap-2 rounded-2xl border border-line/10 px-3 text-[13px] font-medium text-fg [&>svg]:h-4 [&>svg]:w-4 [&>svg]:text-muted">
          {DIRECTION_ICONS[detail.direction]}
          {direction?.title ?? detail.direction}
        </span>
        {detail.notes && (
          <button
            onClick={() => setNotesOpen(true)}
            className="inline-flex h-9 max-w-[280px] items-center gap-2 rounded-2xl border border-line/10 px-3 text-[13px] font-medium text-fg hover:bg-subtle/[0.04]"
          >
            <FileText className="h-4 w-4 text-muted" />
            <span className="truncate">{t("run.notes")}</span>
          </button>
        )}
      </div>
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-3xl bg-bubble px-5 py-2.5 text-[16px] leading-7 sm:max-w-[70%]">
        {detail.topic}
      </div>
      <div className="flex items-center gap-1 text-xs text-faint opacity-0 transition-opacity group-hover:opacity-100">
        <span>{new Date(detail.created_at).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { dateStyle: "medium", timeStyle: "short" })}</span>
        <CopyButton text={detail.topic} />
      </div>
      {detail.notes && (
        <Dialog open={notesOpen} onOpenChange={setNotesOpen} title={t("run.notes")} wide>
          <div className="overflow-y-auto px-6 pb-6">
            <Markdown text={detail.notes} />
          </div>
        </Dialog>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  const [done, setDone] = useState(false);
  return (
    <IconButton
      size="sm"
      label={done ? t("run.copied") : t("run.copy")}
      onClick={async () => {
        await copyText(text);
        setDone(true);
        window.setTimeout(() => setDone(false), 1400);
      }}
    >
      {done ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </IconButton>
  );
}

function StageTurn({
  stage,
  detail,
  events,
  experimentEvents,
  onOpen,
  liveTranscript,
}: {
  stage: ViewStage;
  detail: RunDetail;
  events: RunEvent[];
  experimentEvents: Parameters<typeof ExperimentsContent>[0]["liveEvents"];
  onOpen: (tab: string) => void;
  liveTranscript: AgentTranscript | null;
}) {
  const { t } = useI18n();
  const { navigate } = useRouter();
  const done = stage.status === "done";
  const running = stage.status === "running" && !stage.interrupted;
  const usage = <UsageDetail detail={detail} stage={stage.name} />;
  const stageEvents = useMemo(() => eventsForStage(events, stage.name), [events, stage.name]);
  // Running: the session's live feed. Otherwise its work folded into one line that opens the feed.
  const session = FEED_SESSION[stage.name];
  const feed = running
    ? liveTranscript && <FeedView transcript={liveTranscript} live />
    : session && stage.status !== "pending" && (
        <AgentWork runId={detail.run_id} stage={stage.name} session={session} seconds={stage.interrupted ? null : stage.duration_s} />
      );

  switch (stage.name) {
    case "plan":
      return (
        <StageBlock stage={stage} details={usage} live={feed || undefined}>
          {done && <PlanContent detail={detail} onOpen={onOpen} />}
        </StageBlock>
      );
    case "survey":
      return (
        <StageBlock
          stage={stage}
          details={
            <div className="space-y-3">
              <SurveyDetails stage={stage} />
              {usage}
            </div>
          }
        >
          {done && <SurveyContent stage={stage} onOpen={onOpen} />}
        </StageBlock>
      );
    case "experiments":
      return (
        <StageBlock stage={stage} details={usage}>
          {(done || running || stage.interrupted) && <ExperimentsContent runId={detail.run_id} stage={stage} liveEvents={experimentEvents} onOpen={onOpen} />}
        </StageBlock>
      );
    case "analysis":
      return (
        <StageBlock stage={stage} details={usage}>
          {done && <AnalysisContent runId={detail.run_id} onOpen={onOpen} />}
        </StageBlock>
      );
    case "write":
      return (
        <StageBlock stage={stage} details={usage} live={feed || undefined}>
          {(done || stageEvents.some((e) => e.kind === "write.section" || e.kind === "agent.edit")) && <WriteContent stage={stage} events={stageEvents} />}
        </StageBlock>
      );
    case "review":
      return (
        <StageBlock
          stage={stage}
          details={usage}
          live={running ? (
            <div className="space-y-3">
              <ReviewLive events={stageEvents} />
              {feed}
            </div>
          ) : feed || undefined}
        >
          {done && <ReviewContent detail={detail} events={stageEvents} onOpen={onOpen} />}
        </StageBlock>
      );
    case "evolve": {
      const s = stage.summary as { lessons?: number; active?: number };
      return (
        <StageBlock stage={stage} details={usage}>
          {done && typeof s.lessons === "number" && (
            <p className="text-[15px] text-muted">
              {t("run.evolveSummary", { n: s.lessons, active: s.active ?? 0 })}{" "}
              <button onClick={() => navigate("/lessons")} className="font-medium text-fg underline decoration-line/30 underline-offset-4 hover:decoration-fg">
                {t("nav.lessons")}
              </button>
            </p>
          )}
        </StageBlock>
      );
    }
    case "package":
      return (
        <StageBlock stage={stage} details={usage}>
          {done && detail.paper && (
            <div className="space-y-3">
              <p className="text-[16px] leading-7">{detail.paper.unverified ? t("run.packagedUnverified") : t("package.ready")}</p>
              <PaperCard detail={detail} onOpen={onOpen} />
            </div>
          )}
        </StageBlock>
      );
    default:
      return <StageBlock stage={stage} details={usage} />;
  }
}

/** Events that belong to the latest attempt of one stage (between its last stage.running and the next stage). */
function eventsForStage(events: RunEvent[], stage: StageName): RunEvent[] {
  let start = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].kind === "stage.running" && events[i].stage === stage) {
      start = i;
      break;
    }
  }
  if (start < 0) return [];
  const out: RunEvent[] = [];
  for (let i = start + 1; i < events.length; i++) {
    const e = events[i];
    if (e.kind === "stage.running" && e.stage !== stage) break;
    out.push(e);
  }
  return out;
}

function ReviewLive({ events }: { events: RunEvent[] }) {
  const { t } = useI18n();
  const rounds = events.filter((e) => e.kind === "review.round");
  const builds = events.filter((e) => e.kind === "build").length;
  if (!rounds.length && !builds) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {rounds.map((r) => (
        <Badge key={r.seq} tone={r.accepted ? "ok" : "neutral"}>
          {r.accepted ? <Check className="h-3 w-3" /> : <RotateCcw className="h-3 w-3" />}
          {t("review.round", { n: Number(r.round) })}
          {typeof r.delta === "number" && <span className="tabular-nums">{r.delta >= 0 ? "+" : ""}{(r.delta as number).toFixed(2)}</span>}
        </Badge>
      ))}
    </div>
  );
}

/* ---------- Phase cards (plan approval, failure, interruption) ---------- */

function useResume(detail: RunDetail, reload: () => void) {
  const { t } = useI18n();
  const toast = useToast();
  const { upsertRun, refreshRuns } = useStore();
  const [busy, setBusy] = useState(false);
  const resume = async (body: ResumeRequest, message = t("toast.resumed")) => {
    setBusy(true);
    try {
      await api.resume(detail.run_id, body);
      upsertRun({ ...detail, status: "running" });
      toast("success", message);
      window.setTimeout(reload, 600);
      void refreshRuns();
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { resume, busy };
}

function PhaseCard({ phase, detail, reload, onOpen }: { phase: Phase; detail: RunDetail; reload: () => void; onOpen: (tab: string) => void }) {
  const { t } = useI18n();
  const { resume, busy } = useResume(detail, reload);
  const [allowGateFailures, setAllowGateFailures] = useState(false);

  if (phase.kind === "plan-review") {
    return (
      <Card icon={<PauseCircle className="h-5 w-5 text-info" />} title={t("run.planReady")} body={t("run.planReadyBody")}>
        <Button variant="primary" loading={busy} icon={<Play className="h-4 w-4" />} onClick={() => resume({}, t("toast.approved"))}>
          {t("run.approvePlan")}
        </Button>
        <Button variant="outline" onClick={() => onOpen("plan")}>
          {t("panel.plan")}
        </Button>
        <span className="basis-full text-xs text-faint">{t("run.replanHint")}</span>
      </Card>
    );
  }
  if (phase.kind === "paused") {
    return (
      <Card
        icon={<PauseCircle className="h-5 w-5 text-muted" />}
        title={phase.after ? t("stage.pausedAfter", { stage: t(`stage.${phase.after}` as MessageKey) }) : t("status.pending")}
      >
        <Button variant="primary" loading={busy} icon={<Play className="h-4 w-4" />} onClick={() => resume({})}>
          {t("run.continue")}
        </Button>
      </Card>
    );
  }
  if (phase.kind === "failed") {
    const gateFailure = phase.stage.name === "package" || /gate/i.test(phase.stage.error ?? "");
    return (
      <Card
        tone="bad"
        icon={<AlertOctagon className="h-5 w-5 text-bad" />}
        title={t("run.failedTitle", { stage: t(`stage.${phase.stage.name}` as MessageKey) })}
        body={
          phase.stage.error ? (
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-subtle/[0.04] p-3 font-mono text-[12.5px] leading-5 text-fg/85">
              {phase.stage.error}
            </pre>
          ) : undefined
        }
      >
        <Button
          variant="primary"
          loading={busy}
          icon={<RotateCcw className="h-4 w-4" />}
          onClick={() => resume({ allow_gate_failures: gateFailure && allowGateFailures })}
        >
          {t("run.retry", { stage: t(`stage.${phase.stage.name}` as MessageKey) })}
        </Button>
        <Button variant="outline" onClick={() => onOpen("log")}>
          {t("panel.log")}
        </Button>
        {gateFailure && (
          <label className="flex basis-full items-center gap-2.5 pt-1 text-[13px] text-muted">
            <Switch checked={allowGateFailures} onChange={setAllowGateFailures} label={t("run.allowGateFailures")} />
            {t("run.allowGateFailures")}
          </label>
        )}
      </Card>
    );
  }
  if (phase.kind === "stopped") {
    const name = phase.stage?.name;
    return (
      <Card
        tone="warn"
        icon={<PauseCircle className="h-5 w-5 text-warn" />}
        title={name ? t("run.interruptedTitle", { stage: t(`stage.${name}` as MessageKey) }) : t("stage.interrupted")}
        body={t("run.interruptedBody")}
      >
        <Button variant="primary" loading={busy} icon={<Play className="h-4 w-4" />} onClick={() => resume({})}>
          {t("run.resume")}
        </Button>
        <Button variant="outline" onClick={() => onOpen("log")}>
          {t("panel.log")}
        </Button>
      </Card>
    );
  }
  if (phase.kind === "pending") {
    return (
      <Card icon={<History className="h-5 w-5 text-muted" />} title={t("status.pending")}>
        <Button variant="primary" loading={busy} icon={<Play className="h-4 w-4" />} onClick={() => resume({})}>
          {t("run.resume")}
        </Button>
      </Card>
    );
  }
  return null;
}

function Card({
  icon,
  title,
  body,
  children,
  tone = "neutral",
}: {
  icon: ReactNode;
  title: ReactNode;
  body?: ReactNode;
  children?: ReactNode;
  tone?: "neutral" | "bad" | "warn";
}) {
  return (
    <div
      className={clsx(
        "animate-fade-in rounded-3xl border p-5",
        tone === "bad" ? "border-bad/25" : tone === "warn" ? "border-warn/30" : "border-line/10",
      )}
      role={tone === "bad" ? "alert" : undefined}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold">{title}</div>
          {typeof body === "string" ? <p className="mt-1 text-sm leading-6 text-muted">{body}</p> : body}
          {children && <div className="mt-4 flex flex-wrap items-center gap-2">{children}</div>}
        </div>
      </div>
    </div>
  );
}

/* ---------- Bottom dock: the composer in control mode ---------- */

/** Operator messages of a run, refreshed when one is delivered or sent. */
function useOperatorMessages(runId: string, events: RunEvent[], active: boolean) {
  const [messages, setMessages] = useState<OperatorMessage[]>([]);
  const delivered = useMemo(() => events.filter((e) => e.kind === "operator.delivered").length, [events]);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    api
      .messages(runId)
      .then((m) => !cancelled && setMessages(m))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [runId, delivered, nonce, active]);
  return { messages, add: (m: OperatorMessage) => setMessages((all) => [...all, m]), refresh: () => setNonce((n) => n + 1) };
}

function ControlDock({
  detail,
  phase,
  reload,
  events,
  feedSession,
  liveTranscript,
}: {
  detail: RunDetail;
  phase: Phase;
  reload: () => void;
  events: RunEvent[];
  feedSession: string | undefined;
  liveTranscript: AgentTranscript | null;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const { confirm, upsertRun } = useStore();
  const { resume, busy } = useResume(detail, reload);
  const [notes, setNotes] = useState("");
  const [stopping, setStopping] = useState(false);
  const running = phase.kind === "running";
  useTicker(running);
  useEffect(() => {
    if (!running) setStopping(false);
  }, [running]);
  const operator = useOperatorMessages(detail.run_id, events, running);
  const queued = operator.messages.filter((m) => m.status === "queued");
  const [steer, setSteer] = useState("");
  const [sending, setSending] = useState(false);
  const send = async () => {
    const text = steer.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      operator.add(await api.sendMessage(detail.run_id, text));
      setSteer("");
      toast("info", t("steer.sent"));
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    } finally {
      setSending(false);
    }
  };

  const stop = async () => {
    const ok = await confirm({ title: t("run.stopConfirm"), body: t("run.stopBody"), confirmLabel: t("run.stop"), destructive: true });
    if (!ok) return;
    setStopping(true);
    try {
      await api.stop(detail.run_id);
      toast("info", t("toast.stopping"));
      upsertRun({ ...detail, status: "stopped" });
    } catch (e) {
      setStopping(false);
      toast("error", t("common.error"), (e as Error).message);
    }
  };

  const rerunFrom = async (stage: StageName) => {
    const ok = await confirm({
      title: t("run.rerunConfirm", { stage: t(`stage.${stage}` as MessageKey) }),
      body: t("run.rerunBody", { stage: t(`stage.${stage}` as MessageKey) }),
      confirmLabel: t("run.rerun"),
    });
    if (ok) await resume({ from_stage: stage });
  };

  const replan = async () => {
    const text = notes.trim();
    if (!text) return;
    const merged = detail.notes?.trim() ? `${detail.notes.trim()}\n\n${text}` : text;
    await resume({ from_stage: "plan", stop_after: "plan", notes: merged }, t("toast.replanning"));
    setNotes("");
  };

  const lastDone = STAGES.filter((s) => detail.stages.find((x) => x.name === s)?.status === "done");
  const stage = phase.kind === "running" ? phase.stage : undefined;
  const elapsed = stage ? elapsedSince(stage.running_at) : null;

  const rerunMenu = lastDone.length > 0 && !running && (
    <MenuRoot>
      <MenuTrigger asChild>
        <button className="flex h-9 items-center gap-1.5 rounded-full border border-line/10 px-3 text-[13px] font-medium text-fg hover:bg-subtle/[0.05] data-[state=open]:bg-subtle/[0.05]">
          <RotateCcw className="h-4 w-4" />
          <span className="hidden sm:inline">{t("run.resumeFrom")}</span>
        </button>
      </MenuTrigger>
      <MenuContent side="top" align="start" className="w-[240px]">
        <MenuLabel>{t("run.resumeFrom")}</MenuLabel>
        {STAGES.slice(0, Math.min(STAGES.length, STAGES.indexOf(lastDone[lastDone.length - 1]) + 2)).map((s) => (
          <MenuItem key={s} onSelect={() => rerunFrom(s)}>
            {t(`stage.${s}` as MessageKey)}
          </MenuItem>
        ))}
      </MenuContent>
    </MenuRoot>
  );

  return (
    <div className="shrink-0 px-3 pb-3 md:px-6">
      <div className="mx-auto w-full max-w-[768px]">
        {phase.kind === "plan-review" ? (
          <PlanNotesComposer value={notes} onChange={setNotes} onSubmit={replan} busy={busy} footer={rerunMenu} />
        ) : (
          running ? (
            <div className="space-y-2">
              <div className="px-3">
                {feedSession ? (
                  <AgentStatus transcript={liveTranscript} session={feedSession} />
                ) : (
                  <span className="flex min-w-0 items-center gap-2 text-[13.5px]">
                    <span className="shimmer-text truncate font-medium">{stage ? t(`stageDoing.${stage.name}` as MessageKey) : t("status.running")}</span>
                    {elapsed != null && <span className="shrink-0 tabular-nums text-faint">{formatDuration(elapsed, t)}</span>}
                  </span>
                )}
              </div>
              {queued.length > 0 && (
                <div className="flex flex-col items-end gap-1.5 px-1">
                  {queued.map((m) => (
                    <div key={m.id} className="max-w-[85%] rounded-3xl border border-dashed border-line/15 px-4 py-2 text-[14.5px] leading-6 text-muted sm:max-w-[70%]">
                      <div className="whitespace-pre-wrap break-words">{m.text}</div>
                      <div className="mt-0.5 text-[11.5px] text-faint">{feedSession ? t("steer.queued") : t("steer.queuedIdle")}</div>
                    </div>
                  ))}
                </div>
              )}
              <SteerComposer value={steer} onChange={setSteer} onSend={send} sending={sending} onStop={stop} stopping={stopping} />
            </div>
          ) : (
          <div className="flex min-h-[60px] items-center gap-2 rounded-4xl bg-composer py-2.5 pl-5 pr-2.5 shadow-composer dark:shadow-none">
            <div className="min-w-0 flex-1 text-[15px]">
              <span className="block truncate text-faint">
                {phase.kind === "done" ? t("run.doneControl", { when: relativeTime(detail.updated_at, t) }) : t("composer.followup")}
              </span>
            </div>
            {rerunMenu}
            {phase.kind !== "done" && (
              <Tooltip content={t("run.resume")}>
                <button
                  onClick={() => resume({})}
                  disabled={busy}
                  aria-label={t("run.resume")}
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-inverse text-on-inverse transition-opacity hover:opacity-80 disabled:opacity-50"
                >
                  <Play className="ml-0.5 h-4 w-4 fill-current" />
                </button>
              </Tooltip>
            )}
          </div>
          )
        )}
        <p className="px-4 pt-2 text-center text-xs text-faint">{t("home.disclaimer")}</p>
      </div>
    </div>
  );
}

function PlanNotesComposer({
  value,
  onChange,
  onSubmit,
  busy,
  footer,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  footer: ReactNode;
}) {
  const { t } = useI18n();
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutoGrow(ref, value, 240);
  const canSend = value.trim().length >= 3 && !busy;
  return (
    <div className="flex flex-col rounded-4xl bg-composer shadow-composer focus-within:shadow-[0_0_0_1px_rgb(var(--line)/0.16),0_6px_22px_rgb(0_0_0/0.06)] dark:shadow-none">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        placeholder={t("run.replanPlaceholder")}
        aria-label={t("run.replanPlaceholder")}
        className="max-h-60 min-h-[52px] w-full resize-none bg-transparent px-5 pb-1 pt-[15px] text-[16px] leading-6 text-fg outline-none placeholder:text-faint"
      />
      <div className="flex items-center gap-1.5 px-2.5 pb-2.5 pt-1.5">
        {footer}
        <div className="flex-1" />
        <Tooltip content={t("run.replan")}>
          <button
            onClick={() => canSend && onSubmit()}
            disabled={!canSend}
            aria-label={t("run.replan")}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-inverse text-on-inverse transition-opacity hover:opacity-80 disabled:bg-subtle/15 disabled:text-main disabled:opacity-100 dark:disabled:bg-subtle/20 dark:disabled:text-[#303030]"
          >
            <ArrowUp className="h-5 w-5" strokeWidth={2.2} />
          </button>
        </Tooltip>
      </div>
    </div>
  );
}

/** The composer while a run works: messages to the agents (delivered at their next turn) and Stop. */
function SteerComposer({
  value,
  onChange,
  onSend,
  sending,
  onStop,
  stopping,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  sending: boolean;
  onStop: () => void;
  stopping: boolean;
}) {
  const { t } = useI18n();
  const ref = useRef<HTMLTextAreaElement>(null);
  useAutoGrow(ref, value, 200);
  const canSend = value.trim().length > 0 && !sending;
  return (
    <div className="flex flex-col rounded-4xl bg-composer shadow-composer focus-within:shadow-[0_0_0_1px_rgb(var(--line)/0.16),0_6px_22px_rgb(0_0_0/0.06)] dark:shadow-none">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            if (canSend) onSend();
          }
        }}
        placeholder={t("steer.placeholder")}
        aria-label={t("steer.placeholder")}
        maxLength={4000}
        className="max-h-52 min-h-[52px] w-full resize-none bg-transparent px-5 pb-1 pt-[15px] text-[16px] leading-6 text-fg outline-none placeholder:text-faint"
      />
      <div className="flex items-center gap-1.5 px-2.5 pb-2.5 pt-1">
        <span className="min-w-0 truncate pl-2.5 text-[12px] text-faint">{t("steer.hint")}</span>
        <div className="flex-1" />
        <Tooltip content={t("run.stop")}>
          <button
            onClick={onStop}
            disabled={stopping}
            aria-label={t("run.stop")}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-line/15 text-fg transition-colors hover:bg-subtle/[0.06] disabled:opacity-50"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        </Tooltip>
        <Tooltip content={t("steer.send")}>
          <button
            onClick={() => canSend && onSend()}
            disabled={!canSend}
            aria-label={t("steer.send")}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-inverse text-on-inverse transition-opacity hover:opacity-80 disabled:bg-subtle/15 disabled:text-main disabled:opacity-100 dark:disabled:bg-subtle/20 dark:disabled:text-[#303030]"
          >
            <ArrowUp className="h-5 w-5" strokeWidth={2.2} />
          </button>
        </Tooltip>
      </div>
    </div>
  );
}
