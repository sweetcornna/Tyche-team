import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Meta, ModelsResponse, RunSummary } from "../api/types";

export type SettingsTab = "general" | "model" | "literature" | "workspace" | "about";

interface ConfirmOptions {
  title: string;
  body?: string;
  confirmLabel?: string;
  destructive?: boolean;
}

interface Store {
  meta: Meta | undefined;
  metaError: ApiError | undefined;
  reloadMeta: () => Promise<void>;
  setMeta: (m: Meta) => void;
  runs: RunSummary[];
  runsLoaded: boolean;
  runsError: ApiError | undefined;
  refreshRuns: () => Promise<void>;
  upsertRun: (r: RunSummary) => void;
  models: ModelsResponse | undefined;
  loadModels: () => void;
  searchOpen: boolean;
  setSearchOpen: (v: boolean) => void;
  settingsOpen: boolean;
  settingsTab: SettingsTab;
  openSettings: (tab?: SettingsTab) => void;
  closeSettings: () => void;
  shortcutsOpen: boolean;
  setShortcutsOpen: (v: boolean) => void;
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
  confirmState: (ConfirmOptions & { resolve: (v: boolean) => void }) | null;
}

const StoreContext = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta>();
  const [metaError, setMetaError] = useState<ApiError>();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [runsError, setRunsError] = useState<ApiError>();
  const [models, setModels] = useState<ModelsResponse>();
  const [searchOpen, setSearchOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("general");
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [confirmState, setConfirmState] = useState<Store["confirmState"]>(null);
  const modelsRequested = useRef(false);

  const reloadMeta = useCallback(async () => {
    try {
      setMeta(await api.meta());
      setMetaError(undefined);
    } catch (e) {
      setMetaError(e as ApiError);
    }
  }, []);

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await api.runs(false));
      setRunsError(undefined);
    } catch (e) {
      setRunsError(e as ApiError);
    } finally {
      setRunsLoaded(true);
    }
  }, []);

  const upsertRun = useCallback((r: RunSummary) => {
    setRuns((all) => {
      const i = all.findIndex((x) => x.run_id === r.run_id);
      if (r.archived) return all.filter((x) => x.run_id !== r.run_id);
      if (i < 0) return [r, ...all];
      const next = all.slice();
      next[i] = { ...all[i], ...r };
      return next;
    });
  }, []);

  const loadModels = useCallback(() => {
    if (modelsRequested.current) return;
    modelsRequested.current = true;
    api
      .models()
      .then(setModels)
      .catch(() => {
        modelsRequested.current = false;
      });
  }, []);

  useEffect(() => {
    void reloadMeta();
    void refreshRuns();
  }, [reloadMeta, refreshRuns]);

  // Keep the sidebar live: poll faster while something is running, and when the tab regains focus.
  const anyRunning = runs.some((r) => r.status === "running");
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshRuns();
    }, anyRunning ? 4000 : 15000);
    const onFocus = () => void refreshRuns();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [anyRunning, refreshRuns]);

  const confirm = useCallback(
    (opts: ConfirmOptions) => new Promise<boolean>((resolve) => setConfirmState({ ...opts, resolve })),
    [],
  );

  const openSettings = useCallback((tab: SettingsTab = "general") => {
    setSettingsTab(tab);
    setSettingsOpen(true);
  }, []);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);

  const value = useMemo<Store>(
    () => ({
      meta,
      metaError,
      reloadMeta,
      setMeta,
      runs,
      runsLoaded,
      runsError,
      refreshRuns,
      upsertRun,
      models,
      loadModels,
      searchOpen,
      setSearchOpen,
      settingsOpen,
      settingsTab,
      openSettings,
      closeSettings,
      shortcutsOpen,
      setShortcutsOpen,
      confirm,
      confirmState: confirmState
        ? {
            ...confirmState,
            resolve: (v: boolean) => {
              confirmState.resolve(v);
              setConfirmState(null);
            },
          }
        : null,
    }),
    [
      meta,
      metaError,
      reloadMeta,
      runs,
      runsLoaded,
      runsError,
      refreshRuns,
      upsertRun,
      models,
      loadModels,
      searchOpen,
      settingsOpen,
      settingsTab,
      openSettings,
      closeSettings,
      shortcutsOpen,
      confirm,
      confirmState,
    ],
  );
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore outside StoreProvider");
  return ctx;
}
