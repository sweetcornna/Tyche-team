import clsx from "clsx";
import { Check, ChevronDown, Menu as MenuIcon, RefreshCw, Search, Settings2, SquarePen } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useMediaQuery } from "../lib/hooks";
import { useI18n, type MessageKey } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { useRouter } from "../lib/router";
import { useStore } from "../lib/store";
import { IconButton, MenuContent, MenuItem, MenuLabel, MenuRoot, MenuSeparator, MenuTrigger, Spinner } from "./ui";

/** Top bar of the main column: mobile nav on the left, page-specific content, actions on the right. */
export function Header({ left, right, className }: { left?: ReactNode; right?: ReactNode; className?: string }) {
  const { t } = useI18n();
  const mobile = useMediaQuery("(max-width: 767px)");
  const { setSidebarOpen } = usePrefs();
  const { navigate } = useRouter();
  return (
    <header className={clsx("sticky top-0 z-10 flex h-[52px] shrink-0 items-center gap-1 bg-main/95 px-2 backdrop-blur-sm md:px-3", className)}>
      {mobile && (
        <IconButton label={t("nav.expand")} onClick={() => setSidebarOpen(true)}>
          <MenuIcon className="h-5 w-5" />
        </IconButton>
      )}
      <div className="flex min-w-0 flex-1 items-center">{left}</div>
      <div className="flex shrink-0 items-center gap-1">{right}</div>
      {mobile && (
        <IconButton label={t("nav.new")} onClick={() => navigate("/")}>
          <SquarePen className="h-5 w-5" />
        </IconButton>
      )}
    </header>
  );
}

const EFFORT_ORDER = ["low", "medium", "high", "xhigh", "max"];

export function effortLabel(effort: string | null | undefined, t: (k: MessageKey) => string) {
  if (!effort) return t("model.default");
  return effort === "xhigh" ? "XHigh" : effort.charAt(0).toUpperCase() + effort.slice(1);
}

/** Model + reasoning-effort picker for new runs. */
export function ModelPicker() {
  const { t } = useI18n();
  const { meta, models, modelsLoading, loadModels, openSettings } = useStore();
  const { model, setModel, effort, setEffort } = usePrefs();
  const [filter, setFilter] = useState("");

  const configured = meta?.model.model_name ?? "";
  const activeModel = model ?? configured;
  const activeEffort = effort ?? meta?.model.reasoning_effort ?? null;
  const levels = useMemo(() => {
    const fromMeta = meta?.reasoning_levels ?? EFFORT_ORDER;
    return EFFORT_ORDER.filter((l) => fromMeta.includes(l));
  }, [meta]);

  const list = useMemo(() => {
    const ids = [...(models?.models ?? [])];
    for (const id of [configured, activeModel]) if (id && !ids.some((m) => m.id === id)) ids.unshift({ id });
    const q = filter.trim().toLowerCase();
    return ids.filter((m) => !q || m.id.toLowerCase().includes(q));
  }, [models, configured, activeModel, filter]);

  return (
    <MenuRoot onOpenChange={(open) => open && loadModels()}>
      <MenuTrigger asChild>
        <button aria-label={t("model.title")} data-testid="model-picker-trigger" className="flex h-9 min-w-0 items-center gap-1.5 rounded-lg px-2.5 text-[17px] font-medium text-fg hover:bg-subtle/[0.06] data-[state=open]:bg-subtle/[0.06]">
          <span className="truncate">{activeModel || "Tyche"}</span>
          {activeEffort && <span className="truncate text-muted">{effortLabel(activeEffort, t)}</span>}
          <ChevronDown className="h-4 w-4 shrink-0 text-faint" />
        </button>
      </MenuTrigger>
      <MenuContent className="w-[320px] max-w-[calc(100vw-20px)]" align="start">
        <MenuLabel>{models?.source === "config" ? t("model.fromConfig") : t("model.fromEndpoint")}</MenuLabel>
        {models?.error && <p role="alert" className="px-2.5 py-1 text-xs text-warn">{models.error}</p>}
        {(models?.models.length ?? 0) > 8 && (
          <div className="mx-1 mb-1 flex items-center gap-2 rounded-lg border border-line/10 px-2">
            <Search className="h-4 w-4 text-faint" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
              placeholder={t("model.filter")}
              aria-label={t("model.filter")}
              className="h-8 w-full bg-transparent text-sm outline-none placeholder:text-faint"
            />
          </div>
        )}
        <div className="max-h-[260px] overflow-y-auto">
          {modelsLoading && (
            <div className="flex items-center gap-2 px-2.5 py-2 text-sm text-faint">
              <Spinner className="h-3.5 w-3.5" /> {t("common.loading")}
            </div>
          )}
          {list.map((m) => (
            <MenuItem
              key={m.id}
              onSelect={(e) => {
                e.preventDefault();
                setModel(m.id === configured ? null : m.id);
              }}
              hint={m.context_length ? t("model.context", { n: `${Math.round(m.context_length / 1000)}k` }) : undefined}
            >
              <span className="flex items-center gap-2">
                <span className="truncate">{m.id}</span>
                {m.id === activeModel && <Check className="h-4 w-4 shrink-0" />}
              </span>
            </MenuItem>
          ))}
        </div>
        {!list.length && !modelsLoading && <p className="px-2.5 py-2 text-xs text-faint">{t("model.noMatches")}</p>}
        <MenuItem icon={<RefreshCw />} disabled={modelsLoading} onSelect={(e) => { e.preventDefault(); loadModels(true); }}>
          {t("model.refresh")}
        </MenuItem>
        <MenuItem icon={<Settings2 />} onSelect={() => openSettings("model")}>{t("settings.model")}</MenuItem>
        <MenuSeparator />
        <MenuLabel>{t("model.effort")}</MenuLabel>
        <MenuItem
          onSelect={(e) => {
            e.preventDefault();
            setEffort(null);
          }}
        >
          <span className="flex items-center justify-between">
            {t("model.default")}
            {!effort && <Check className="h-4 w-4" />}
          </span>
        </MenuItem>
        {levels.map((level) => (
          <MenuItem
            key={level}
            onSelect={(e) => {
              e.preventDefault();
              setEffort(level);
            }}
          >
            <span className="flex items-center justify-between gap-3">
              <span>
                <span className="block">{effortLabel(level, t)}</span>
                <span className="block text-xs text-faint">{t(`model.effortHint.${level}` as MessageKey)}</span>
              </span>
              {effort === level && <Check className="h-4 w-4 shrink-0" />}
            </span>
          </MenuItem>
        ))}
        <MenuSeparator />
        <p className="px-2.5 pb-1.5 pt-0.5 text-xs leading-5 text-faint">{t("model.appliesToNew")}</p>
      </MenuContent>
    </MenuRoot>
  );
}
