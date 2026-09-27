import clsx from "clsx";
import { ExternalLink, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useRef, type ReactNode } from "react";
import type { ExperimentEvent, RunDetail, RunEvent } from "../../api/types";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { usePrefs } from "../../lib/prefs";
import { IconButton, Spinner } from "../ui";

export const PANEL_TABS = [
  "paper",
  "plan",
  "sources",
  "experiments",
  "results",
  "review",
  "claims",
  "revisions",
  "lineage",
  "report",
  "files",
  "log",
] as const;
export type PanelTab = (typeof PANEL_TABS)[number];

const DocTabs = lazy(() => import("./DocTabs"));
const SourcesTab = lazy(() => import("./SourcesTab"));
const ExperimentsTab = lazy(() => import("./ExperimentsTab"));
const ResultsReviewTabs = lazy(() => import("./ResultsReviewTabs"));
const TraceTabs = lazy(() => import("./TraceTabs"));
const FilesTab = lazy(() => import("./FilesTab"));

export interface TabProps {
  runId: string;
  detail: RunDetail;
  events: RunEvent[];
  experimentEvents: ExperimentEvent[];
  onTab: (tab: string) => void;
}

const MIN_WIDTH = 380;

/** Resizable side panel with the run's evidence: paper, plan, sources, code, results, review, and trace views. */
export function RightPanel({
  runId,
  detail,
  tab,
  onTab,
  onClose,
  events,
  experimentEvents,
  overlay,
}: TabProps & { tab: PanelTab; onClose: () => void; overlay: boolean }) {
  const { t } = useI18n();
  const { panelWidth, setPanelWidth } = usePrefs();
  const panel = useRef<HTMLElement>(null);
  const strip = useRef<HTMLDivElement>(null);

  const clamp = useCallback((w: number) => Math.round(Math.max(MIN_WIDTH, Math.min(w, window.innerWidth - 420))), []);

  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = panel.current?.getBoundingClientRect().width ?? panelWidth;
    const move = (ev: PointerEvent) => {
      const w = clamp(startW + (startX - ev.clientX));
      if (panel.current) panel.current.style.width = `${w}px`;
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      setPanelWidth(clamp(startW + (startX - ev.clientX)));
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // Keep the active tab visible in the strip.
  useEffect(() => {
    strip.current?.querySelector<HTMLElement>(`[data-tab="${tab}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector("[role=dialog],[role=menu]")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const props: TabProps = { runId, detail, events, experimentEvents, onTab };
  let body: ReactNode;
  switch (tab) {
    case "paper":
    case "plan":
    case "report":
    case "log":
      body = <DocTabs tab={tab} {...props} />;
      break;
    case "sources":
      body = <SourcesTab {...props} />;
      break;
    case "experiments":
      body = <ExperimentsTab {...props} />;
      break;
    case "results":
    case "review":
      body = <ResultsReviewTabs tab={tab} {...props} />;
      break;
    case "claims":
    case "revisions":
    case "lineage":
      body = <TraceTabs tab={tab} {...props} />;
      break;
    case "files":
      body = <FilesTab {...props} />;
      break;
  }

  return (
    <>
      {overlay && <div className="fixed inset-0 z-30 animate-fade-in bg-black/30" onClick={onClose} />}
      <aside
        ref={panel}
        className={clsx(
          "flex min-w-0 flex-col bg-main",
          overlay
            ? "fixed inset-y-0 right-0 z-40 w-full max-w-[640px] animate-slide-in-right shadow-menu"
            : "relative h-full shrink-0 border-l border-line/[0.08]",
        )}
        style={overlay ? undefined : { width: clamp(panelWidth) }}
        aria-label={t(`panel.${tab}` as MessageKey)}
      >
        {!overlay && (
          <div
            onPointerDown={startResize}
            onDoubleClick={() => setPanelWidth(560)}
            className="group absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize"
            role="separator"
            aria-orientation="vertical"
          >
            <div className="mx-auto h-full w-px bg-transparent transition-colors group-hover:bg-accent/60" />
          </div>
        )}
        <div className="flex h-[52px] shrink-0 items-center gap-1 border-b border-line/[0.06] pl-2 pr-2">
          <div ref={strip} className="no-scrollbar flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto" role="tablist">
            {PANEL_TABS.map((name) => (
              <button
                key={name}
                data-tab={name}
                role="tab"
                aria-selected={tab === name}
                onClick={() => onTab(name)}
                className={clsx(
                  "h-8 shrink-0 rounded-lg px-2.5 text-[13px] font-medium transition-colors",
                  tab === name ? "bg-subtle/[0.07] text-fg" : "text-muted hover:bg-subtle/[0.04] hover:text-fg",
                  name === "paper" && !detail.paper && "opacity-50",
                )}
              >
                {t(`panel.${name}` as MessageKey)}
              </button>
            ))}
          </div>
          {tab === "paper" && detail.paper && (
            <IconButton size="sm" label={t("panel.openNew")} onClick={() => window.open(detail.paper!.url, "_blank", "noopener")}>
              <ExternalLink className="h-4 w-4" />
            </IconButton>
          )}
          <IconButton size="sm" label={t("panel.close")} shortcut="Esc" onClick={onClose}>
            <X className="h-5 w-5" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <Suspense fallback={<PanelLoading />}>{body}</Suspense>
        </div>
      </aside>
    </>
  );
}

export function PanelLoading() {
  const { t } = useI18n();
  return (
    <div className="flex h-full items-center justify-center gap-2 text-sm text-faint">
      <Spinner className="h-4 w-4" /> {t("panel.loading")}
    </div>
  );
}

/** Scrollable body with consistent padding for text-like tabs. */
export function PanelScroll({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("h-full overflow-y-auto px-5 pb-10 pt-4", className)}>{children}</div>;
}

export function PanelMessage({ children }: { children: ReactNode }) {
  return <div className="flex h-full items-center justify-center px-8 text-center text-sm text-faint">{children}</div>;
}
