import * as DialogPrimitive from "@radix-ui/react-dialog";
import clsx from "clsx";
import { FileText, Search, SquarePen } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { RunSummary } from "../../api/types";
import { relativeTime } from "../../lib/format";
import { useI18n, type MessageKey } from "../../lib/i18n";
import { useRouter } from "../../lib/router";
import { useStore } from "../../lib/store";
import { StatusDot } from "../ui";

function score(run: RunSummary, q: string): number {
  if (!q) return 1;
  const hay = `${run.title} ${run.topic} ${run.method ?? ""} ${run.run_id} ${run.direction}`.toLowerCase();
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  let s = 0;
  for (const term of terms) {
    const i = hay.indexOf(term);
    if (i < 0) return 0;
    s += i < run.title.length ? 3 : 1;
  }
  return s;
}

export function SearchDialog() {
  const { t } = useI18n();
  const { searchOpen, setSearchOpen, runs } = useStore();
  const { navigate } = useRouter();
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (searchOpen) {
      setQ("");
      setCursor(0);
    }
  }, [searchOpen]);

  const results = useMemo(() => {
    return runs
      .map((r) => ({ r, s: score(r, q.trim()) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s || Date.parse(b.r.updated_at) - Date.parse(a.r.updated_at))
      .slice(0, 50)
      .map((x) => x.r);
  }, [runs, q]);

  // Row 0 is "New research"; rows 1..n are runs.
  const total = results.length + 1;
  const go = (index: number) => {
    setSearchOpen(false);
    if (index === 0) navigate("/");
    else navigate(`/r/${encodeURIComponent(results[index - 1].run_id)}`);
  };

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  return (
    <DialogPrimitive.Root open={searchOpen} onOpenChange={setSearchOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[70] animate-fade-in bg-black/40 dark:bg-black/60" />
        <DialogPrimitive.Content
          className="fixed left-1/2 top-[12vh] z-[71] flex max-h-[70vh] w-[calc(100vw-32px)] max-w-[640px] -translate-x-1/2 animate-pop-in flex-col overflow-hidden rounded-3xl bg-elevated shadow-menu outline-none"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(total - 1, c + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(0, c - 1));
            } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              go(cursor);
            }
          }}
        >
          <DialogPrimitive.Title className="sr-only">{t("nav.search")}</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">{t("search.placeholder")}</DialogPrimitive.Description>
          <div className="flex items-center gap-3 border-b border-line/[0.08] px-5">
            <Search className="h-5 w-5 shrink-0 text-faint" />
            <input
              autoFocus
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setCursor(e.target.value ? 1 : 0);
              }}
              placeholder={t("search.placeholder")}
              className="h-14 w-full bg-transparent text-[15px] outline-none placeholder:text-faint"
            />
          </div>
          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto p-2">
            <Row index={0} active={cursor === 0} onHover={setCursor} onClick={() => go(0)}>
              <SquarePen className="h-[18px] w-[18px] text-fg" />
              <span className="flex-1">{t("nav.new")}</span>
            </Row>
            {results.length > 0 && <div className="px-3 pb-1 pt-3 text-xs font-medium text-faint">{q ? t("nav.runs") : t("search.recent")}</div>}
            {results.map((r, i) => (
              <Row key={r.run_id} index={i + 1} active={cursor === i + 1} onHover={setCursor} onClick={() => go(i + 1)}>
                <FileText className="h-[18px] w-[18px] shrink-0 text-muted" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{r.title}</span>
                  <span className="block truncate text-xs text-faint">
                    {t(`status.${r.status}` as MessageKey)} · {r.method ?? r.direction} · {relativeTime(r.updated_at, t)}
                  </span>
                </span>
                <StatusDot status={r.status} />
              </Row>
            ))}
            {q && results.length === 0 && <div className="px-3 py-8 text-center text-sm text-faint">{t("search.empty")}</div>}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function Row({
  index,
  active,
  onHover,
  onClick,
  children,
}: {
  index: number;
  active: boolean;
  onHover: (i: number) => void;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      data-index={index}
      onMouseMove={() => onHover(index)}
      onClick={onClick}
      className={clsx("flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm", active && "bg-subtle/[0.06]")}
    >
      {children}
    </button>
  );
}
