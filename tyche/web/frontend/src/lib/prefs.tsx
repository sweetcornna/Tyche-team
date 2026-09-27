import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useMediaQuery } from "./hooks";

export type Theme = "system" | "light" | "dark";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw == null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable (private mode) — preferences just don't persist */
  }
}

/** A value persisted in localStorage (per-browser convenience state only). */
export function usePersistent<T>(key: string, fallback: T): [T, (v: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => read(key, fallback));
  const set = useCallback(
    (v: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
        write(key, next);
        return next;
      });
    },
    [key],
  );
  return [value, set];
}

function applyTheme(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

interface Prefs {
  theme: Theme;
  setTheme: (t: Theme) => void;
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean | ((p: boolean) => boolean)) => void;
  panelWidth: number;
  setPanelWidth: (w: number) => void;
  /** Model and effort for new runs; null = the configured default. */
  model: string | null;
  setModel: (m: string | null) => void;
  effort: string | null;
  setEffort: (e: string | null) => void;
}

const PrefsContext = createContext<Prefs | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    try {
      const t = localStorage.getItem("tyche.theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  // The desktop sidebar state is remembered; the phone drawer always starts closed.
  const [desktopOpen, setDesktopOpen] = usePersistent("tyche.sidebar", true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const mobile = useMediaQuery("(max-width: 767px)");
  const sidebarOpen = mobile ? drawerOpen : desktopOpen;
  const setSidebarOpen = useCallback(
    (v: boolean | ((p: boolean) => boolean)) => (mobile ? setDrawerOpen(v) : setDesktopOpen(v)),
    [mobile, setDesktopOpen],
  );
  const [panelWidth, setPanelWidth] = usePersistent("tyche.panelWidth", 560);
  const [model, setModel] = usePersistent<string | null>("tyche.model", null);
  const [effort, setEffort] = usePersistent<string | null>("tyche.effort", null);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem("tyche.theme", t);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const value = useMemo(
    () => ({ theme, setTheme, sidebarOpen, setSidebarOpen, panelWidth, setPanelWidth, model, setModel, effort, setEffort }),
    [theme, setTheme, sidebarOpen, setSidebarOpen, panelWidth, setPanelWidth, model, setModel, effort, setEffort],
  );
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs() {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error("usePrefs outside PrefsProvider");
  return ctx;
}
