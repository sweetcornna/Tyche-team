import clsx from "clsx";
import {
  Archive,
  BookOpen,
  CircleHelp,
  Ellipsis,
  Keyboard,
  Lightbulb,
  PanelLeft,
  Pencil,
  Pin,
  PinOff,
  Search,
  Settings,
  SquarePen,
  Stethoscope,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { RunSummary } from "../api/types";
import { groupRuns } from "../lib/format";
import { isMac, useMediaQuery } from "../lib/hooks";
import { useI18n, type MessageKey } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { Link, useRouter } from "../lib/router";
import { useStore } from "../lib/store";
import { useToast } from "../lib/toast";
import { ArchivedDialog } from "./dialogs/ArchivedDialog";
import { LogoMark } from "./Logo";
import { IconButton, MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuTrigger, Spinner, Tooltip } from "./ui";

const mod = isMac ? "⌘" : "Ctrl+";
const shift = isMac ? "⇧" : "Shift+";

export function Sidebar() {
  const { sidebarOpen, setSidebarOpen } = usePrefs();
  const mobile = useMediaQuery("(max-width: 767px)");
  const { route } = useRouter();

  // On phones the sidebar is a drawer that closes after navigating.
  useEffect(() => {
    if (mobile) setSidebarOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, mobile]);

  if (mobile) {
    return (
      <>
        {sidebarOpen && <div className="fixed inset-0 z-40 animate-fade-in bg-black/40" onClick={() => setSidebarOpen(false)} />}
        <aside
          className={clsx(
            "fixed inset-y-0 left-0 z-50 w-[280px] bg-sidebar transition-transform duration-200",
            sidebarOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <SidebarFull />
        </aside>
      </>
    );
  }
  return (
    <aside
      className={clsx(
        "relative z-20 h-full shrink-0 overflow-hidden border-r border-line/[0.06] bg-sidebar transition-[width] duration-200 ease-out",
        sidebarOpen ? "w-[260px]" : "w-[52px]",
      )}
    >
      {sidebarOpen ? <SidebarFull /> : <SidebarRail />}
    </aside>
  );
}

function SidebarRail() {
  const { t } = useI18n();
  const { setSidebarOpen } = usePrefs();
  const { setSearchOpen } = useStore();
  const { navigate } = useRouter();
  return (
    <div className="flex h-full flex-col items-center gap-1 py-2">
      <Tooltip content={t("nav.expand")} side="right" shortcut={`${shift}${mod}S`}>
        <button
          className="group flex h-9 w-9 items-center justify-center rounded-lg text-fg hover:bg-subtle/[0.06]"
          onClick={() => setSidebarOpen(true)}
          aria-label={t("nav.expand")}
        >
          <LogoMark className="h-[22px] w-[22px] group-hover:hidden" />
          <PanelLeft className="hidden h-5 w-5 text-muted group-hover:block" />
        </button>
      </Tooltip>
      <div className="h-2" />
      <IconButton label={t("nav.new")} shortcut={`${shift}${mod}O`} onClick={() => navigate("/")}>
        <SquarePen className="h-5 w-5" />
      </IconButton>
      <IconButton label={t("nav.search")} shortcut={`${mod}K`} onClick={() => setSearchOpen(true)}>
        <Search className="h-5 w-5" />
      </IconButton>
      <IconButton label={t("nav.library")} onClick={() => navigate("/library")}>
        <BookOpen className="h-5 w-5" />
      </IconButton>
      <IconButton label={t("nav.lessons")} onClick={() => navigate("/lessons")}>
        <Lightbulb className="h-5 w-5" />
      </IconButton>
      <div className="flex-1" />
      <AccountMenu compact />
    </div>
  );
}

function SidebarFull() {
  const { t } = useI18n();
  const { setSidebarOpen } = usePrefs();
  const { runs, runsLoaded, setSearchOpen } = useStore();
  const { route } = useRouter();
  const grouped = useMemo(() => groupRuns(runs), [runs]);
  const activeId = route.name === "run" ? route.id : null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-[52px] shrink-0 items-center justify-between px-2">
        <Link to="/" className="flex h-9 items-center gap-2 rounded-lg px-2 text-fg hover:bg-subtle/[0.06]" aria-label="Tyche">
          <LogoMark className="h-[22px] w-[22px]" />
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Tyche</span>
        </Link>
        <IconButton label={t("nav.collapse")} shortcut={`${shift}${mod}S`} onClick={() => setSidebarOpen(false)}>
          <PanelLeft className="h-5 w-5" />
        </IconButton>
      </div>

      <nav className="shrink-0 px-2 pb-2">
        <NavItem to="/" icon={<SquarePen />} label={t("nav.new")} hint={`${shift}${mod}O`} active={route.name === "home"} />
        <NavButton icon={<Search />} label={t("nav.search")} hint={`${mod}K`} onClick={() => setSearchOpen(true)} />
        <NavItem to="/library" icon={<BookOpen />} label={t("nav.library")} active={route.name === "library"} />
        <NavItem to="/lessons" icon={<Lightbulb />} label={t("nav.lessons")} active={route.name === "lessons"} />
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {grouped.pinned.length > 0 && <RunGroup label={t("nav.pinned")} runs={grouped.pinned} activeId={activeId} />}
        {grouped.groups.map((g) => (
          <RunGroup key={g.group} label={t(`group.${g.group}` as MessageKey)} runs={g.runs} activeId={activeId} />
        ))}
        {runsLoaded && runs.length === 0 && <p className="px-2.5 pt-4 text-[13px] leading-5 text-faint">{t("nav.noRuns")}</p>}
        {!runsLoaded && (
          <div className="space-y-2 px-2.5 pt-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-4 animate-pulse-soft rounded bg-subtle/[0.05]" style={{ width: `${55 + ((i * 17) % 40)}%` }} />
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-line/[0.06] p-2">
        <AccountMenu />
      </div>
    </div>
  );
}

function NavItem({ to, icon, label, hint, active }: { to: string; icon: JSX.Element; label: string; hint?: string; active?: boolean }) {
  return (
    <Link
      to={to}
      className={clsx(
        "group flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm text-fg transition-colors hover:bg-subtle/[0.06]",
        active && "bg-subtle/[0.06]",
      )}
    >
      <span className="text-fg [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>
      <span className="flex-1 truncate">{label}</span>
      {hint && <span className="hidden text-xs text-faint group-hover:inline">{hint}</span>}
    </Link>
  );
}

function NavButton({ icon, label, hint, onClick }: { icon: JSX.Element; label: string; hint?: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm text-fg transition-colors hover:bg-subtle/[0.06]"
    >
      <span className="[&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>
      <span className="flex-1 truncate">{label}</span>
      {hint && <span className="hidden text-xs text-faint group-hover:inline">{hint}</span>}
    </button>
  );
}

function RunGroup({ label, runs, activeId }: { label: string; runs: RunSummary[]; activeId: string | null }) {
  return (
    <div className="mt-4 first:mt-2">
      <div className="sticky top-0 z-[1] bg-sidebar px-2.5 pb-1.5 pt-1 text-xs font-medium text-faint">{label}</div>
      <ul>
        {runs.map((r) => (
          <RunItem key={r.run_id} run={r} active={r.run_id === activeId} />
        ))}
      </ul>
    </div>
  );
}

function RunItem({ run, active }: { run: RunSummary; active: boolean }) {
  const { t } = useI18n();
  const { upsertRun, refreshRuns, confirm } = useStore();
  const { navigate } = useRouter();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [draft, setDraft] = useState(run.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(run.title);
      requestAnimationFrame(() => inputRef.current?.select());
    }
  }, [editing, run.title]);

  const commitRename = async () => {
    setEditing(false);
    const title = draft.trim();
    if (!title || title === run.title) return;
    try {
      upsertRun(await api.patch(run.run_id, { title }));
      toast("success", t("toast.renamed"));
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    }
  };

  const patch = async (body: { pinned?: boolean; archived?: boolean }, message?: MessageKey) => {
    try {
      const updated = await api.patch(run.run_id, body);
      upsertRun(updated);
      if (message) toast("success", t(message));
      if (body.archived && active) navigate("/");
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    }
  };

  const remove = async () => {
    const ok = await confirm({ title: t("run.deleteConfirm"), body: t("run.deleteBody"), confirmLabel: t("run.delete"), destructive: true });
    if (!ok) return;
    try {
      await api.remove(run.run_id);
      toast("success", t("toast.deleted"));
      if (active) navigate("/");
      await refreshRuns();
    } catch (e) {
      toast("error", t("common.error"), (e as Error).message);
    }
  };

  if (editing) {
    return (
      <li className="px-0.5 py-0.5">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) void commitRename();
            if (e.key === "Escape") setEditing(false);
          }}
          maxLength={200}
          className="h-9 w-full rounded-lg border border-line/20 bg-main px-2 text-sm outline-none"
        />
      </li>
    );
  }

  return (
    <li className="group relative">
      <Link
        to={`/r/${encodeURIComponent(run.run_id)}`}
        title={run.title}
        className={clsx(
          "flex h-9 items-center gap-2 rounded-lg pl-2.5 pr-2 text-sm transition-colors",
          active ? "bg-subtle/[0.08]" : "hover:bg-subtle/[0.05]",
          menuOpen && "bg-subtle/[0.05]",
        )}
      >
        <span className="relative min-w-0 flex-1 overflow-hidden whitespace-nowrap [mask-image:linear-gradient(to_right,black_85%,transparent)]">
          {run.title}
        </span>
        <RunIndicator run={run} hidden={menuOpen} />
      </Link>
      <MenuRoot open={menuOpen} onOpenChange={setMenuOpen}>
        <MenuTrigger asChild>
          <button
            aria-label={t("run.more")}
            className={clsx(
              "absolute right-1.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-muted hover:text-fg",
              menuOpen ? "flex" : "hidden group-hover:flex",
              active ? "bg-transparent" : "",
            )}
          >
            <Ellipsis className="h-[18px] w-[18px]" />
          </button>
        </MenuTrigger>
        <MenuContent align="start" side="bottom" className="min-w-[180px]">
          <MenuItem icon={<Pencil />} onSelect={() => setTimeout(() => setEditing(true), 0)}>
            {t("run.rename")}
          </MenuItem>
          <MenuItem icon={run.pinned ? <PinOff /> : <Pin />} onSelect={() => patch({ pinned: !run.pinned })}>
            {run.pinned ? t("run.unpin") : t("run.pin")}
          </MenuItem>
          <MenuItem icon={<Archive />} onSelect={() => patch({ archived: true }, "toast.archived")}>
            {t("run.archive")}
          </MenuItem>
          <MenuSeparator />
          <MenuItem icon={<Trash2 />} danger disabled={run.status === "running"} onSelect={remove}>
            {t("run.delete")}
          </MenuItem>
        </MenuContent>
      </MenuRoot>
    </li>
  );
}

function RunIndicator({ run, hidden }: { run: RunSummary; hidden?: boolean }) {
  const { t } = useI18n();
  if (hidden) return <span className="w-5" />;
  const label = t(`status.${run.status}` as MessageKey);
  if (run.status === "running")
    return (
      <span className="flex w-5 justify-center group-hover:invisible" title={label}>
        <Spinner className="h-3.5 w-3.5 text-info" />
      </span>
    );
  if (run.status === "failed" || run.status === "stopped" || run.status === "paused")
    return (
      <span className="flex w-5 justify-center group-hover:invisible" title={label}>
        <span className={clsx("h-1.5 w-1.5 rounded-full", run.status === "failed" ? "bg-bad" : "bg-warn")} />
      </span>
    );
  return <span className="w-0 group-hover:w-5" />;
}

function AccountMenu({ compact }: { compact?: boolean }) {
  const { t } = useI18n();
  const { meta, openSettings, setShortcutsOpen } = useStore();
  const [archivedOpen, setArchivedOpen] = useState(false);
  const effort = meta?.model.reasoning_effort;
  const modelLine = meta ? `${meta.model.model_name}${effort ? ` · ${effort}` : ""}` : "…";
  return (
    <>
      <MenuRoot>
        <MenuTrigger asChild>
          {compact ? (
            <button className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-subtle/[0.06]" aria-label={t("nav.settings")}>
              <Avatar />
            </button>
          ) : (
            <button className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left hover:bg-subtle/[0.06]">
              <Avatar />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{t("nav.settings")}</span>
                <span className="block truncate text-xs text-faint">{modelLine}</span>
              </span>
            </button>
          )}
        </MenuTrigger>
        <MenuContent side="top" align="start" className="w-[240px]">
          <div className="px-2.5 pb-1.5 pt-1 text-xs text-faint">
            <div className="truncate" title={meta?.workspace}>
              {meta?.workspace ?? "…"}
            </div>
          </div>
          <MenuSeparator />
          <MenuItem icon={<Settings />} onSelect={() => openSettings("general")} hint={`${mod},`}>
            {t("nav.settings")}
          </MenuItem>
          <MenuItem icon={<Stethoscope />} onSelect={() => openSettings("workspace")}>
            {t("settings.diagnostics")}
          </MenuItem>
          <MenuItem icon={<Archive />} onSelect={() => setArchivedOpen(true)}>
            {t("nav.archived")}
          </MenuItem>
          <MenuItem icon={<Keyboard />} onSelect={() => setShortcutsOpen(true)} hint={`${mod}/`}>
            {t("settings.shortcuts")}
          </MenuItem>
          <MenuSeparator />
          <MenuItem icon={<CircleHelp />} onSelect={() => openSettings("about")}>
            {t("settings.about")}
          </MenuItem>
        </MenuContent>
      </MenuRoot>
      <ArchivedLazy open={archivedOpen} onOpenChange={setArchivedOpen} />
    </>
  );
}

function Avatar() {
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-inverse text-on-inverse">
      <LogoMark className="h-[18px] w-[18px]" />
    </span>
  );
}

function ArchivedLazy(props: { open: boolean; onOpenChange: (v: boolean) => void }) {
  return props.open ? <ArchivedDialog {...props} /> : null;
}
