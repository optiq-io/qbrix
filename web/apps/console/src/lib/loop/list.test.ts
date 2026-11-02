import { describe, expect, it } from "vitest";
import type { ChangeEntry, LoopListItem } from "@/lib/api/types";
import {
  alertCount,
  latestEvent,
  listStatus,
  orderLoops,
  pausesByLoop,
  rowTime,
  searchLoops,
  shareSegments,
  workspaceCounters,
  workspaceCounts,
  workspaceEvents,
} from "./list";

function loop(key: string, overrides: Partial<LoopListItem> = {}): LoopListItem {
  return {
    id: key,
    key,
    name: key.toUpperCase(),
    purpose: "",
    metric: { id: "m", name: "clicked", type: "conversion", window_seconds: 3600 },
    engine: "spinoza",
    state: "live",
    paused_from: null,
    live_since: null,
    owner: { id: "u", name: "Ada" },
    fallback: "a",
    options: [
      { id: "1", key: "a", name: "Option A" },
      { id: "2", key: "b", name: "Option B" },
    ],
    cycle: null,
    updated_at: "2026-11-01T10:00:00Z",
    latest_change: null,
    results: null,
    ...overrides,
  };
}

function pause(id: string, loopId: string, actor: "qbrix" | "member", at = "2026-11-01T03:12:00Z"): ChangeEntry {
  return {
    id,
    kind: "loop.pause",
    at,
    status: "applied",
    reason: null,
    evidence: null,
    target: { type: "loop", id: loopId, key: loopId, name: loopId },
    pieces: [
      { kind: "actor", actor: { kind: actor, name: null, on_behalf_of: null, via: null }, text: null, name: null },
    ],
    diff: [],
    undone_by: null,
    verb: "changed",
    request_id: null,
    undoable: true,
    not_undoable_reason: null,
    ids: [],
    count: 1,
    first_at: at,
  };
}

function results(share: (number | null)[], lift: number | null = null, rate = 0): LoopListItem["results"] {
  return {
    share: share.map((value, at) => ({ key: "abcde"[at], share: value })),
    lift,
    early: false,
    decisions_per_second: rate,
  };
}

const FIVE = ["a", "b", "c", "d", "e"].map((key) => ({ id: key, key, name: key.toUpperCase() }));

describe("orderLoops", () => {
  it("puts paused first, then drafts, then live, newest first within each", () => {
    const ordered = orderLoops([
      loop("live-old", { updated_at: "2026-10-01T00:00:00Z" }),
      loop("draft", { state: "draft" }),
      loop("live-new", { updated_at: "2026-11-01T00:00:00Z" }),
      loop("paused", { state: "paused", updated_at: "2026-01-01T00:00:00Z" }),
    ]);
    expect(ordered.map((item) => item.key)).toEqual(["paused", "draft", "live-new", "live-old"]);
  });
});

describe("searchLoops", () => {
  const loops = [loop("checkout", { name: "Checkout headline" }), loop("search-rank", { name: "Ranking" })];

  it("matches a name or a key, ignoring case and spaces", () => {
    expect(searchLoops(loops, " HEADLINE ").map((item) => item.key)).toEqual(["checkout"]);
    expect(searchLoops(loops, "search-").map((item) => item.key)).toEqual(["search-rank"]);
  });

  it("keeps everything for an empty query", () => {
    expect(searchLoops(loops, "  ")).toHaveLength(2);
  });
});

describe("listStatus", () => {
  it("warms up until a live loop has a lift, and a lift of zero counts", () => {
    expect(listStatus({ state: "live", results: results([1], null) })).toBe("warming_up");
    expect(listStatus({ state: "live", results: null })).toBe("warming_up");
    expect(listStatus({ state: "live", results: results([1], 0) })).toBe("live");
  });

  it("leaves other states alone", () => {
    expect(listStatus({ state: "draft", results: null })).toBe("draft");
    expect(listStatus({ state: "paused", results: results([1], 0.2) })).toBe("paused");
  });
});

describe("the workspace's header", () => {
  const loops = [
    loop("a", { results: results([1], 0.1, 1.5) }),
    loop("b", { results: results([1], null, 0.5) }),
    loop("c", { state: "paused" }),
    loop("d", { state: "draft" }),
  ];

  it("counts each status", () => {
    expect(workspaceCounts(loops)).toEqual({ learning: 1, warmingUp: 1, paused: 1, drafts: 1 });
  });

  it("sums the rate and says when more loops exist", () => {
    expect(workspaceCounters(loops, false)).toEqual({ loops: "4", rate: "2" });
    expect(workspaceCounters(loops, true).loops).toBe("4+");
  });
});

describe("shareSegments", () => {
  it("is null for a draft and before any decision", () => {
    expect(shareSegments(loop("a"))).toBeNull();
    expect(shareSegments(loop("a", { results: results([null, null]) }))).toBeNull();
  });

  it("orders up to three options by share, with no others", () => {
    const segments = shareSegments(loop("a", { results: results([0.25, 0.75]) }));
    expect(segments?.map(({ name, rank, share }) => [name, rank, share])).toEqual([
      ["Option B", 0, 0.75],
      ["Option A", 1, 0.25],
    ]);
  });

  it("folds the rest into others past three, naming what it holds", () => {
    const segments = shareSegments(loop("a", { options: FIVE, results: results([0.05, 0.4, 0.3, 0.2, 0.05]) }));
    expect(segments?.map(({ key }) => key)).toEqual(["b", "c", "d", "others"]);
    expect(segments?.[3].rank).toBe(3);
    expect(segments?.[3].share).toBeCloseTo(0.1);
    expect(segments?.[3].members).toEqual([
      { name: "A", share: 0.05 },
      { name: "E", share: 0.05 },
    ]);
  });
});

describe("latestEvent", () => {
  const change = {
    id: "c",
    kind: "loop.launch",
    verb: "launched",
    at: null,
    who: { kind: "member", user_id: "u", name: "Ada" },
    via: null,
  } as const;

  it("reads who, the verb and it", () => {
    expect(latestEvent(change)).toBe("Ada launched it.");
    expect(latestEvent({ ...change, who: { kind: "qbrix", user_id: null, name: null }, verb: "paused" })).toBe(
      "qbrix paused it.",
    );
  });

  it("names the client for a connection", () => {
    expect(latestEvent({ ...change, via: { connection_id: "x", client: "Claude Code" } })).toBe(
      "Claude Code launched it.",
    );
  });
});

describe("rowTime", () => {
  const now = new Date(2026, 10, 2, 12, 0).getTime();

  it("is a time today, a day this week and a date otherwise", () => {
    expect(rowTime(new Date(2026, 10, 2, 3, 12).toISOString(), now)).toBe("03:12");
    expect(rowTime(new Date(2026, 9, 31, 9, 0).toISOString(), now)).toBe("Sat");
    expect(rowTime(new Date(2026, 9, 4, 9, 0).toISOString(), now)).toBe("4 Oct");
    expect(rowTime(null, now)).toBe("");
  });
});

describe("alerts", () => {
  const paused = loop("paused", { state: "paused" });

  it("reads the newest pause, so a person's later pause clears qbrix's alert", () => {
    const entries = [pause("new", "paused", "member", "2026-11-02T00:00:00Z"), pause("old", "paused", "qbrix")];
    expect(alertCount(pausesByLoop([paused], entries))).toBe(0);
  });

  it("counts qbrix's pause, however the loop changed since", () => {
    expect(alertCount(pausesByLoop([paused], [pause("p", "paused", "qbrix")]))).toBe(1);
  });

  it("ignores a pause on a loop that has resumed", () => {
    expect(pausesByLoop([loop("paused")], [pause("p", "paused", "qbrix")]).size).toBe(0);
  });

  it("keeps an open alert older than the recent changes, and hides other kinds of target", () => {
    const entries = [pause("p", "paused", "qbrix")];
    const pool = { ...pause("x", "pool", "member"), kind: "pool.update", target: { type: "pool", id: "x", key: null, name: "x" } };
    const events = workspaceEvents([pool], entries, pausesByLoop([paused], entries));
    expect(events.map((event) => [event.id, event.alert])).toEqual([["p", true]]);
  });
});
