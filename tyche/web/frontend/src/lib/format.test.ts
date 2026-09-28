import { describe, expect, it } from "vitest";
import { dateGroup, formatDuration, formatMetric, formatP, formatTokens, groupRuns, safeUrl } from "./format";
import { translate } from "./i18n";
import type { RunSummary } from "../api/types";

const t = (key: Parameters<typeof translate>[1], vars?: Record<string, string | number>) => translate("en", key, vars);

const run = (id: string, updated: string, pinned = false): RunSummary => ({
  run_id: id,
  title: id,
  topic: id,
  direction: "memory_engine",
  created_at: updated,
  updated_at: updated,
  status: "done",
  stage: "package",
  stages_done: 8,
  stages_total: 8,
  method: null,
  synthetic: false,
  has_paper: true,
  composite: null,
  unverified: false,
  pinned,
  archived: false,
  process: null,
});

describe("formatDuration", () => {
  it("formats seconds, minutes and hours", () => {
    expect(formatDuration(42, t)).toBe("42s");
    expect(formatDuration(258.2, t)).toBe("4m 18s");
    expect(formatDuration(7500, t)).toBe("2h 05m");
    expect(formatDuration(null, t)).toBe("");
  });
});

describe("dateGroup / groupRuns", () => {
  const now = new Date(2026, 8, 27, 15, 0, 0);
  it("buckets by calendar day", () => {
    expect(dateGroup(new Date(2026, 8, 27, 1).toISOString(), now)).toBe("today");
    expect(dateGroup(new Date(2026, 8, 26, 23).toISOString(), now)).toBe("yesterday");
    expect(dateGroup(new Date(2026, 8, 22).toISOString(), now)).toBe("week");
    expect(dateGroup(new Date(2026, 8, 1).toISOString(), now)).toBe("month");
    expect(dateGroup(new Date(2025, 0, 1).toISOString(), now)).toBe("older");
    expect(dateGroup("not a date", now)).toBe("older");
  });
  it("puts pinned runs first and sorts newest first", () => {
    const runs = [
      run("a", new Date(2026, 8, 27, 9).toISOString()),
      run("b", new Date(2026, 8, 27, 12).toISOString()),
      run("c", new Date(2026, 8, 20).toISOString(), true),
      run("d", new Date(2026, 8, 26, 10).toISOString()),
    ];
    const grouped = groupRuns(runs, now);
    expect(grouped.pinned.map((r) => r.run_id)).toEqual(["c"]);
    expect(grouped.groups.map((g) => g.group)).toEqual(["today", "yesterday"]);
    expect(grouped.groups[0].runs.map((r) => r.run_id)).toEqual(["b", "a"]);
  });
});

describe("number formatting", () => {
  it("formats tokens compactly", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1500)).toBe("1.5k");
    expect(formatTokens(105635)).toBe("106k");
    expect(formatTokens(2_345_678)).toBe("2.35M");
  });
  it("formats metrics and p-values", () => {
    expect(formatMetric(0.8)).toBe("0.800");
    expect(formatMetric(890.017)).toBe("890.0");
    expect(formatMetric(12.345)).toBe("12.35");
    expect(formatMetric(null)).toBe("–");
    expect(formatP(0.0002)).toBe("<0.001");
    expect(formatP(0.3101)).toBe("0.310");
  });
});

import { splitFrontMatter } from "../components/Markdown";

describe("splitFrontMatter", () => {
  it("separates a leading YAML block", () => {
    expect(splitFrontMatter("---\na: 1\nb: 2\n---\n# Title\n")).toEqual({ meta: "a: 1\nb: 2", body: "# Title\n" });
  });
  it("leaves plain markdown and later rules alone", () => {
    expect(splitFrontMatter("# T\n\n---\n\nx")).toEqual({ meta: null, body: "# T\n\n---\n\nx" });
  });
});

describe("translate plurals", () => {
  it("picks the English word form by count", () => {
    expect(translate("en", "claims.nCitations", { n: 1 })).toBe("1 citation");
    expect(translate("en", "claims.nCitations", { n: 3 })).toBe("3 citations");
    expect(translate("zh", "claims.nCitations", { n: 1 })).toBe("1 条引用");
  });
});

describe("safeUrl", () => {
  it("keeps http(s) links and drops every other scheme", () => {
    expect(safeUrl("https://arxiv.org/abs/0000.00001")).toBe("https://arxiv.org/abs/0000.00001");
    expect(safeUrl("http://example.test/a b")).toBe("http://example.test/a%20b");
    expect(safeUrl("javascript:alert(1)")).toBeUndefined();
    expect(safeUrl("data:text/html,x")).toBeUndefined();
    expect(safeUrl("not a url")).toBeUndefined();
    expect(safeUrl(null)).toBeUndefined();
  });
});
