import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import clsx from "clsx";

type Kind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: Kind;
  title: string;
  body?: string;
}

const ToastContext = createContext<(kind: Kind, title: string, body?: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (kind: Kind, title: string, body?: string) => {
      const id = ++seq.current;
      setToasts((all) => [...all.slice(-3), { id, kind, title, body }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 8000 : 3500);
    },
    [dismiss],
  );
  const value = useMemo(() => push, [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 top-3 z-[100] flex flex-col items-center gap-2 px-4"
        role="region"
        aria-live="polite"
      >
        {toasts.map((t) => {
          const Icon = t.kind === "success" ? CheckCircle2 : t.kind === "error" ? AlertCircle : Info;
          return (
            <div
              key={t.id}
              className="pointer-events-auto flex max-w-md animate-pop-in items-start gap-2.5 rounded-2xl bg-elevated px-4 py-3 text-sm shadow-menu"
            >
              <Icon
                className={clsx("mt-0.5 h-4 w-4 shrink-0", {
                  "text-ok": t.kind === "success",
                  "text-bad": t.kind === "error",
                  "text-info": t.kind === "info",
                })}
              />
              <div className="min-w-0">
                <div className="font-medium">{t.title}</div>
                {t.body && <div className="mt-0.5 break-words text-muted">{t.body}</div>}
              </div>
              <button
                className="-mr-1 ml-1 rounded-md p-0.5 text-faint hover:text-fg"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
