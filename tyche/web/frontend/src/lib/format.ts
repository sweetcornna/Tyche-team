import type { T } from "./i18n";
import type { RunSummary, StageName } from "../api/types";

export const STAGES: StageName[] = ["plan", "survey", "experiments", "analysis", "write", "review", "evolve", "package"];

export function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/** Compact human duration: 42s, 4m 18s, 2h 05m. */
export function formatDuration(seconds: number | null | undefined, t: T): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  const s = Math.round(seconds);
  if (s < 60) return t("common.seconds", { n: s });
  if (s < 3600) return t("common.minutes", { m: Math.floor(s / 60), s: s % 60 });
  return t("common.hours", { h: Math.floor(s / 3600), m: String(Math.floor((s % 3600) / 60)).padStart(2, "0") });
}

export function relativeTime(value: string | null | undefined, t: T, now = Date.now()): string {
  const ms = parseTime(value);
  if (ms == null) return "";
  const diff = Math.max(0, now - ms) / 1000;
  if (diff < 45) return t("common.justNow");
  if (diff < 3600) return t("common.minutesAgo", { n: Math.max(1, Math.round(diff / 60)) });
  if (diff < 86400) return t("common.hoursAgo", { n: Math.round(diff / 3600) });
  return t("common.daysAgo", { n: Math.round(diff / 86400) });
}

export type DateGroup = "today" | "yesterday" | "week" | "month" | "older";

export function dateGroup(value: string | null | undefined, now = new Date()): DateGroup {
  const ms = parseTime(value);
  if (ms == null) return "older";
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  if (ms >= startOfToday) return "today";
  if (ms >= startOfToday - day) return "yesterday";
  if (ms >= startOfToday - 7 * day) return "week";
  if (ms >= startOfToday - 30 * day) return "month";
  return "older";
}

/** Sidebar grouping: pinned first, then by the date of the last update, newest first. */
export function groupRuns(runs: RunSummary[], now = new Date()) {
  const order: DateGroup[] = ["today", "yesterday", "week", "month", "older"];
  const pinned = runs.filter((r) => r.pinned);
  const buckets = new Map<DateGroup, RunSummary[]>();
  for (const run of runs) {
    if (run.pinned) continue;
    const g = dateGroup(run.updated_at || run.created_at, now);
    if (!buckets.has(g)) buckets.set(g, []);
    buckets.get(g)!.push(run);
  }
  const byNewest = (a: RunSummary, b: RunSummary) =>
    (parseTime(b.updated_at) ?? 0) - (parseTime(a.updated_at) ?? 0);
  return {
    pinned: pinned.sort(byNewest),
    groups: order.filter((g) => buckets.has(g)).map((g) => ({ group: g, runs: buckets.get(g)!.sort(byNewest) })),
  };
}

export function formatTokens(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "–";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(n < 10_000_000 ? 2 : 1)}M`;
}

/** Metric values as the paper would show them: rates with 3 decimals, large counts grouped. */
export function formatMetric(value: number | null | undefined, digits?: number): string {
  if (value == null || !Number.isFinite(value)) return "–";
  const abs = Math.abs(value);
  if (digits != null) return value.toFixed(digits);
  if (abs !== 0 && abs < 0.001) return value.toExponential(2);
  if (abs <= 1) return value.toFixed(3);
  if (abs < 100) return value.toFixed(2);
  if (abs < 10000) return value.toFixed(1);
  return Math.round(value).toLocaleString("en-US");
}

export function formatP(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "–";
  if (p < 0.001) return "<0.001";
  return p.toFixed(3);
}

export function humanize(identifier: string): string {
  return identifier.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function stageIndex(stage: StageName | null | undefined): number {
  return stage ? STAGES.indexOf(stage) : -1;
}

/** Seconds elapsed since an ISO time (live timers). */
export function elapsedSince(value: string | null | undefined, now = Date.now()): number | null {
  const ms = parseTime(value);
  return ms == null ? null : Math.max(0, (now - ms) / 1000);
}
