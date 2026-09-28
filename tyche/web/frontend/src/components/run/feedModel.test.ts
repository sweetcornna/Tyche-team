import { describe, expect, it } from "vitest";
import type { AgentItem } from "../../api/types";
import { buildFeed, groupCounts, headTail, latestPlan, outcomeOf } from "./feedModel";

const ok = (text: string) => ({ ok: true, text });
const todos = (status: string) => JSON.stringify([{ id: "method", content: "Write the method section.", status }]);

const transcript: AgentItem[] = [
  { kind: "task", text: "Write the complete paper." },
  {
    kind: "assistant",
    prose: "",
    calls: [
      { tool: "update_todos", args: { todos: todos("in_progress") }, result: ok("todo list updated") },
      { tool: "read_section", args: { section: "method" }, result: ok("the method section is not written yet") },
      { tool: "update_todos", args: { todos: todos("in_progress") }, result: ok("todo list updated"), duplicate_of: 1 },
    ],
  },
  {
    kind: "assistant",
    prose: "",
    calls: [
      { tool: "lookup_numbers", args: { query: "exact_match" }, result: ok("Registered values:\nproposed.exact_match.mean = 1 (result)\nbaseline.exact_match.mean = 0.25 (result)") },
      { tool: "lookup_numbers", args: { query: "tokens" }, result: ok("no registered value matches; labels look like ...") },
    ],
  },
  {
    kind: "assistant",
    prose: "Now the method section.",
    calls: [
      { tool: "write_section", args: { section: "method", latex: "We pack..." }, result: ok("saved method: 414 words\nchecks for this section:\nno findings") },
      { tool: "update_todos", args: { todos: todos("in_progress") }, result: ok("todo list updated") },
      { tool: "update_todos", args: { todos: todos("completed") }, result: ok("todo list updated") },
    ],
  },
  { kind: "operator", text: "Stress the cost trade-off." },
  { kind: "stop_blocked", text: "sections not written yet: abstract" },
];

describe("buildFeed", () => {
  const feed = buildFeed(transcript);

  it("folds consecutive look-ups across turns into one group and drops repeated calls", () => {
    expect(feed.map((b) => b.type)).toEqual(["task", "plan", "group", "say", "change", "plan", "operator", "handback"]);
    const group = feed[2];
    expect(group.type === "group" && group.calls.map((c) => c.tool)).toEqual(["read_section", "lookup_numbers", "lookup_numbers"]);
    expect(group.type === "group" && groupCounts(group.calls)).toEqual([["read", 1], ["lookup", 2]]);
  });

  it("shows a plan only when it changed", () => {
    expect(feed.filter((b) => b.type === "plan")).toHaveLength(2);
    expect(latestPlan(feed)?.[0].status).toBe("completed");
  });

  it("summarises each call's result in one line", () => {
    const [, , group, , change] = feed;
    if (group.type !== "group" || change.type !== "change") throw new Error("unexpected feed");
    expect(group.calls.map((c) => c.outcome)).toEqual([[{ k: "notWritten" }], [{ k: "values", n: 2 }], [{ k: "noMatch" }]]);
    expect(change.call.outcome).toEqual([{ k: "words", n: 414 }, { k: "noFindings" }]);
  });
});

describe("outcomeOf", () => {
  it("counts gate findings of a build by severity and reports failures by their first line", () => {
    const build = {
      tool: "build_paper",
      args: {},
      result: ok("compiled: True\nmain-text pages: 5 (limit 5)\ngate findings:\n- [major] numbers/analysis: x\n- [minor] style/intro: y"),
    };
    expect(outcomeOf(build)).toEqual([{ k: "pages", n: 5, of: 5 }, { k: "findings", blocker: 0, major: 1, minor: 1 }]);
    const failed = { tool: "edit_section", args: {}, result: { ok: false, text: "old text not found in method; copy it exactly\nThe closest line is: ..." } };
    expect(outcomeOf(failed)).toEqual([{ k: "text", text: "old text not found in method; copy it exactly" }]);
    expect(outcomeOf({ tool: "lint", args: {}, result: null })).toEqual([]);
  });
});

describe("headTail", () => {
  it("keeps the head and tail of long output and counts the hidden lines", () => {
    const text = Array.from({ length: 30 }, (_, i) => `line ${i}`).join("\n");
    const { head, hidden, tail } = headTail(text, 6);
    expect([head[0], hidden, tail[tail.length - 1]]).toEqual(["line 0", 18, "line 29"]);
    expect(headTail("a\nb").hidden).toBe(0);
  });
});
