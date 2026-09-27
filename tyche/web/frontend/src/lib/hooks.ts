import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

export interface AsyncState<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
}

/** Fetch data for a component; re-runs when `deps` change; keeps stale data while reloading. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], opts?: { enabled?: boolean; interval?: number }): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const enabled = opts?.enabled ?? true;
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fnRef
      .current()
      .then((value) => {
        if (cancelled) return;
        setData(value);
        setError(undefined);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  useEffect(() => {
    if (!opts?.interval || !enabled) return;
    const id = window.setInterval(() => setNonce((n) => n + 1), opts.interval);
    return () => window.clearInterval(id);
  }, [opts?.interval, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Re-render every `ms` while `active` (live elapsed timers). */
export function useTicker(active: boolean, ms = 1000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setTick((n) => n + 1), ms);
    return () => window.clearInterval(id);
  }, [active, ms]);
}

export const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** Global keyboard shortcuts. `combo` like "mod+k", "mod+shift+o", "escape". */
export function useHotkeys(bindings: Record<string, (e: KeyboardEvent) => void>) {
  const ref = useRef(bindings);
  ref.current = bindings;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      const parts: string[] = [];
      if (isMac ? e.metaKey : e.ctrlKey) parts.push("mod");
      if (e.shiftKey) parts.push("shift");
      if (e.altKey) parts.push("alt");
      parts.push(e.key.toLowerCase());
      const combo = parts.join("+");
      const handler = ref.current[combo];
      if (handler) {
        e.preventDefault();
        handler(e);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => typeof matchMedia !== "undefined" && matchMedia(query).matches);
  useEffect(() => {
    const mq = matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener("change", onChange);
    onChange();
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}
