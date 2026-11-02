import { describe, expect, it } from "vitest";
import type { ChangeActorMark, ChangeEntry } from "@/lib/api/types";
import { byDay, canUndo, panelTime, toHistoryRow, undoConsequence, undoLabel } from "./row";

const NOW = new Date(2026, 9, 29, 15, 0).getTime();

function entry(overrides: Partial<ChangeEntry> = {}, actor: ChangeActorMark = { kind: "member", name: "Ada", on_behalf_of: null, via: null }): ChangeEntry {
  return {
    id: "c1",
    kind: "loop.rename",
    verb: "renamed",
    at: new Date(2026, 9, 29, 14, 2).toISOString(),
    status: "applied",
    reason: null,
    evidence: null,
    request_id: null,
    target: { type: "loop", id: "l1", key: "cta", name: "Pricing CTA" },
    pieces: [
      { kind: "actor", actor, text: null, name: null },
      { kind: "text", actor: null, text: " renamed ", name: null },
      { kind: "loop", actor: null, text: null, name: "Pricing CTA" },
      { kind: "text", actor: null, text: ".", name: null },
    ],
    diff: [],
    undoable: true,
    not_undoable_reason: null,
    undone_by: null,
    count: 1,
    first_at: new Date(2026, 9, 29, 14, 2).toISOString(),
    ids: ["c1"],
    ...overrides,
  };
}

describe("toHistoryRow", () => {
  it("always says the time, since the day is the group's", () => {
    expect(toHistoryRow(entry(), NOW).time).toBe("14:02");
  });

  it("gives a fold its range", () => {
    const fold = entry({ count: 6, first_at: new Date(2026, 9, 29, 11, 20).toISOString(), at: new Date(2026, 9, 29, 11, 28).toISOString() });
    expect(toHistoryRow(fold, NOW).time).toBe("11:20 to 11:28");
  });

  it("says where a change came from when no connection does", () => {
    expect(toHistoryRow(entry(), NOW).context).toBe("in the console");
    const viaKey = entry({}, { kind: "member", name: "Ada", on_behalf_of: null, via: "the API" });
    expect(toHistoryRow(viaKey, NOW).context).toBeUndefined();
    const client = entry({}, { kind: "connection", name: "Cursor", on_behalf_of: "Sam", via: null });
    expect(toHistoryRow(client, NOW).context).toBeUndefined();
  });

  it("marks only a pause with evidence as a safety pause", () => {
    const qbrix: ChangeActorMark = { kind: "qbrix", name: null, on_behalf_of: null, via: null };
    const evidence = { signal: "decision_errors" } as ChangeEntry["evidence"];
    expect(toHistoryRow(entry({ kind: "loop.pause", evidence }, qbrix), NOW).context).toBe("safety pause");
    expect(toHistoryRow(entry({ kind: "loop.pause" }, qbrix), NOW).context).toBeUndefined();
  });

  it("tags an undone change with who undid it", () => {
    const undone = entry({ undone_by: { id: "u1", who: { kind: "member", name: "Mustafa" }, at: "2026-10-29T15:00:00Z" } });
    expect(toHistoryRow(undone, NOW).tag?.label).toBe("Undone by Mustafa");
  });
});

describe("canUndo", () => {
  it("offers undo on a single undoable change", () => {
    expect(canUndo(entry())).toBe(true);
  });

  it("offers none on a fold, even when its newest can be undone", () => {
    expect(canUndo(entry({ count: 6 }))).toBe(false);
  });

  it("offers none once undone, or on a kind that can't be", () => {
    expect(canUndo(entry({ undone_by: { id: "u", who: { kind: "qbrix", name: null }, at: "" } }))).toBe(false);
    expect(canUndo(entry({ undoable: false }))).toBe(false);
  });
});

describe("undoLabel", () => {
  it("names the kind's action", () => {
    expect(undoLabel(entry())).toBe("Undo rename");
  });
});

describe("undoConsequence", () => {
  it("says what undoing each loop and metric kind will do", () => {
    const renamed = entry({ diff: [{ field: "name", before: "Pricing page CTA", after: "Pricing CTA" }] });
    expect(undoConsequence(renamed)).toBe("Renames Pricing CTA back to Pricing page CTA.");
    expect(undoConsequence(entry({ kind: "loop.pause" }))).toBe("Resumes Pricing CTA. It goes back to serving the engine's choices.");
    expect(undoConsequence(entry({ kind: "loop.resume" }))).toBe(
      "Pauses Pricing CTA. Every call gets its fallback until someone resumes it.",
    );
    expect(undoConsequence(entry({ kind: "loop.create" }))).toBe("Deletes Pricing CTA.");
    expect(undoConsequence(entry({ kind: "metric.create" }))).toBe("Deletes Pricing CTA.");
  });

  it("claims nothing for a kind it can't describe", () => {
    expect(undoConsequence(entry({ kind: "gate.patch" }))).toBeNull();
  });
});

describe("panelTime", () => {
  it("reads the day and the time", () => {
    expect(panelTime(entry(), NOW)).toBe("Today at 14:02");
    expect(panelTime(entry({ at: new Date(2026, 9, 28, 9, 12).toISOString() }), NOW)).toBe("Yesterday at 09:12");
    expect(panelTime(entry({ at: new Date(2026, 9, 26, 10, 5).toISOString() }), NOW)).toBe("26 Oct at 10:05");
  });
});

describe("byDay", () => {
  it("groups newest first under the frames' labels", () => {
    const rows = [
      entry({ id: "a" }),
      entry({ id: "b", at: new Date(2026, 9, 29, 9, 0).toISOString() }),
      entry({ id: "c", at: new Date(2026, 9, 28, 16, 40).toISOString() }),
      entry({ id: "d", at: new Date(2026, 9, 26, 10, 5).toISOString() }),
    ];
    const groups = byDay(rows, (row) => row, NOW);
    expect(groups.map((group) => group.label)).toEqual(["Today", "Yesterday", "Monday 26 Oct"]);
    expect(groups[0].items.map((row) => row.id)).toEqual(["a", "b"]);
  });

  it("names the year of an older day", () => {
    const old = entry({ at: new Date(2025, 11, 31, 10, 0).toISOString() });
    expect(byDay([old], (row) => row, NOW)[0].label).toBe("Wednesday 31 Dec 2025");
  });
});
