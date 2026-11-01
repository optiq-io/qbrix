import { describe, expect, it } from "vitest";
import type { ChangeEntry } from "@/lib/api/types";
import { toChangeData, toHeaderEvent, toPin, toRailEntry } from "./event";

const NOW = new Date(2026, 9, 30, 9, 41).getTime();
const AT = new Date(2026, 9, 4, 14, 2);

function entry(overrides: Partial<ChangeEntry> = {}): ChangeEntry {
  return {
    id: "c1",
    kind: "loop.rename",
    at: AT.toISOString(),
    status: "applied",
    reason: "reads better",
    evidence: null,
    pieces: [
      {
        kind: "actor",
        actor: { kind: "connection", name: "Claude Code", on_behalf_of: "Ada", via: null },
        text: null,
        name: null,
      },
      { kind: "text", actor: null, text: " renamed ", name: null },
      { kind: "loop", actor: null, text: null, name: "Checkout headline" },
      { kind: "text", actor: null, text: ".", name: null },
    ],
    diff: [{ field: "name", before: "Old", after: "Checkout headline" }],
    undone_by: null,
    count: 1,
    first_at: AT.toISOString(),
    ...overrides,
  };
}

describe("toHeaderEvent", () => {
  it("pins an alert, with its reason as context and no chips", () => {
    const event = toHeaderEvent(entry(), true);
    expect(event).toMatchObject({ alert: true, context: "reads better", diff: [] });
    expect(event.reason).toBeUndefined();
  });

  it("isn't an alert unless asked", () => {
    const event = toHeaderEvent(entry());
    expect(event.alert).toBeUndefined();
    expect(event.context).toBeUndefined();
  });

  it("keeps the sentence's order and maps the actor", () => {
    const event = toHeaderEvent(entry());
    expect(event.pieces[0]).toEqual({
      kind: "actor",
      actor: { kind: "connection", name: "Claude Code", onBehalfOf: "Ada" },
    });
    expect(event.pieces.slice(1)).toEqual([
      { kind: "text", text: " renamed " },
      { kind: "loop", name: "Checkout headline" },
      { kind: "text", text: "." },
    ]);
    expect(event.source).toBe("Claude Code");
    expect(event.firstAt).toBeUndefined();
  });

  it("marks a fold with when it began", () => {
    const first = new Date(2026, 9, 4, 14, 0);
    expect(toHeaderEvent(entry({ count: 3, first_at: first.toISOString() })).firstAt).toBe(first.getTime());
  });
});

describe("toChangeData", () => {
  it("splits the sentence into who, verb and target", () => {
    const change = toChangeData(entry(), NOW);
    expect(change.verb).toBe("renamed");
    expect(change.target).toEqual({ kind: "loop", name: "Checkout headline" });
    expect(change.time).toBe("14:02");
  });

  it("names who undid it", () => {
    const undone = entry({ undone_by: { id: "c2", who: { kind: "member", name: "Sam" }, at: AT.toISOString() } });
    expect(toChangeData(undone, NOW).tag).toEqual({ label: "Undone by Sam" });
  });
});

describe("toRailEntry", () => {
  it("is live from the cycle's start and sealed before it", () => {
    expect(toRailEntry(entry(), AT.getTime(), NOW).state).toBe("live");
    expect(toRailEntry(entry(), AT.getTime() + 1, NOW).state).toBe("sealed");
  });

  it("reads a date, or the time for today", () => {
    expect(toRailEntry(entry(), 0, NOW).at).toBe("4 Oct");
    expect(toRailEntry(entry(), 0, AT.getTime()).at).toBe("14:02");
  });

  it("ends at the creation and marks a pause", () => {
    expect(toRailEntry(entry({ kind: "loop.create" }), 0, NOW).kind).toBe("origin");
    expect(toRailEntry(entry({ kind: "loop.pause" }), 0, NOW).kind).toBe("pause");
  });
});

describe("toPin", () => {
  it("reads the sentence, then what moved and when", () => {
    const pin = toPin(entry());
    expect(pin.title).toBe("Claude Code renamed Checkout headline.");
    expect(pin.detail).toBe("Old → Checkout headline  ·  4 Oct");
    expect(pin.at).toBe(AT.getTime());
  });
});
