import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleHelp } from "lucide-react";
import { useState, type ReactNode } from "react";

/* Small, single-series charts. Marks follow one spec: thin bars with a 4px rounded data end,
 * 2px lines, >=8px dots with a 2px surface ring, hairline recessive grid, text in text tokens,
 * and a hover tooltip on every mark. Status colors appear only with an icon and a label. */

function HoverTip({ x, y, children }: { x: number | string; y: number; children: ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg bg-[#0d0d0d] px-2.5 py-1.5 text-xs text-white shadow-lg dark:bg-[#f4f4f4] dark:text-[#0d0d0d]"
      style={{ left: x, top: y - 8 }}
    >
      {children}
    </div>
  );
}

/** Horizontal bars on a fixed 0–10 scale (reviewer dimensions). */
export function ScoreBars({
  rows,
  max = 10,
}: {
  rows: { label: string; value: number; detail?: ReactNode }[];
  max?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  return (
    <div className="relative">
      <div className="space-y-2">
        {rows.map((row, i) => {
          const pct = Math.max(0, Math.min(1, row.value / max)) * 100;
          return (
            <div
              key={row.label}
              className="grid grid-cols-[132px_1fr_36px] items-center gap-3 text-[13px]"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              <span className="truncate text-muted" title={row.label}>
                {row.label}
              </span>
              <div className="relative h-[10px]">
                {/* recessive hairline grid at 0, 5, 10 */}
                {[0, 50, 100].map((g) => (
                  <span key={g} className="absolute top-[-3px] h-4 w-px bg-line/[0.08]" style={{ left: `${g}%` }} />
                ))}
                <div
                  className={clsx("absolute inset-y-0 left-0 rounded-r-[4px] bg-accent transition-opacity", hover != null && hover !== i && "opacity-40")}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-right font-medium tabular-nums text-fg">{row.value.toFixed(1)}</span>
              {hover === i && row.detail && (
                <div className="pointer-events-none absolute left-[144px] z-20 -translate-y-[115%] rounded-lg bg-[#0d0d0d] px-2.5 py-1.5 text-xs text-white shadow-lg dark:bg-[#f4f4f4] dark:text-[#0d0d0d]">
                  {row.detail}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Composite score per review round: 2px line with ringed dots; rolled-back rounds are hollow. */
export function RoundTrend({
  points,
  height = 120,
  labelRound,
}: {
  points: { round: number; value: number; accepted: boolean; note?: string }[];
  height?: number;
  labelRound: (round: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length === 0) return null;
  const width = 360;
  const pad = { l: 28, r: 20, t: 16, b: 24 };
  const values = points.map((p) => p.value);
  const lo = Math.max(0, Math.floor(Math.min(...values) - 1));
  const hi = Math.min(10, Math.ceil(Math.max(...values) + 1));
  const x = (i: number) => pad.l + (points.length === 1 ? (width - pad.l - pad.r) / 2 : (i * (width - pad.l - pad.r)) / (points.length - 1));
  const y = (v: number) => pad.t + ((hi - v) / Math.max(1, hi - lo)) * (height - pad.t - pad.b);
  const accepted = points.map((p, i) => ({ ...p, i })).filter((p) => p.accepted);
  const path = accepted.map((p, k) => `${k ? "L" : "M"}${x(p.i)},${y(p.value)}`).join(" ");
  // Evenly spaced ticks: every integer on short ranges, otherwise ends and midpoint.
  const ticks = hi - lo <= 4 ? Array.from({ length: hi - lo + 1 }, (_, i) => lo + i) : [lo, (lo + hi) / 2, hi];
  return (
    <div className="relative w-full max-w-[420px]">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full overflow-visible" role="img" aria-label="Composite score per review round">
        {ticks.map((tv) => (
          <g key={tv}>
            <line x1={pad.l} x2={width - pad.r} y1={y(tv)} y2={y(tv)} className="stroke-line/[0.08]" strokeWidth={1} />
            <text x={pad.l - 8} y={y(tv) + 4} textAnchor="end" className="fill-faint text-[10px]">
              {tv}
            </text>
          </g>
        ))}
        <path d={path} fill="none" className="stroke-accent" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p, i) => (
          <g key={p.round} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} className="cursor-default">
            <circle cx={x(i)} cy={y(p.value)} r={12} fill="transparent" />
            <circle
              cx={x(i)}
              cy={y(p.value)}
              r={4.5}
              strokeWidth={2}
              className={p.accepted ? "fill-accent stroke-main" : "fill-main stroke-faint"}
            />
            <text x={x(i)} y={height - 6} textAnchor="middle" className="fill-faint text-[10px]">
              {labelRound(p.round)}
            </text>
          </g>
        ))}
        {/* label the latest accepted value only */}
        {accepted.length > 0 && (
          <text
            x={x(accepted[accepted.length - 1].i) + 9}
            y={y(accepted[accepted.length - 1].value) - 8}
            className="fill-fg text-[11px] font-semibold"
          >
            {accepted[accepted.length - 1].value.toFixed(2)}
          </text>
        )}
      </svg>
      {hover != null && (
        <HoverTip x={`${(x(hover) / width) * 100}%`} y={0}>
          {labelRound(points[hover].round)} · {points[hover].value.toFixed(2)}
          {points[hover].note ? ` · ${points[hover].note}` : ""}
        </HoverTip>
      )}
    </div>
  );
}

/** Verified / weak / unverified as one stacked bar with 2px surface gaps and an icon legend. */
export function StatusBar({
  parts,
}: {
  parts: { key: "ok" | "warn" | "bad"; label: string; value: number }[];
}) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  const icon = { ok: <CheckCircle2 className="h-3.5 w-3.5 text-ok" />, warn: <AlertTriangle className="h-3.5 w-3.5 text-warn" />, bad: <CircleHelp className="h-3.5 w-3.5 text-bad" /> };
  return (
    <div>
      <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-subtle/[0.05]">
        {total > 0 &&
          parts
            .filter((p) => p.value > 0)
            .map((p) => (
              <div
                key={p.key}
                title={`${p.label}: ${p.value}`}
                className={clsx("h-full first:rounded-l-full last:rounded-r-full", { "bg-ok": p.key === "ok", "bg-warn": p.key === "warn", "bg-bad": p.key === "bad" })}
                style={{ width: `${(p.value / total) * 100}%` }}
              />
            ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {parts.map((p) => (
          <span key={p.key} className="inline-flex items-center gap-1.5">
            {icon[p.key]}
            {p.label}
            <span className="font-medium tabular-nums text-fg">{p.value}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
