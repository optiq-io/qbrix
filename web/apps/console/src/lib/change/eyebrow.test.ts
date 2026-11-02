import { describe, expect, it } from "vitest";
import type { ChangeCounts } from "@/lib/api/types";
import type { EyebrowToken } from "@/lib/header/status";
import { changesEyebrow, whoCounts } from "./eyebrow";

const COUNTS: ChangeCounts = {
  since: "2026-10-26T00:00:00Z",
  total: 53,
  undone: 2,
  who: { member: 9, connection: 41, qbrix: 3 },
  clients: [
    { name: "Claude Code", count: 34 },
    { name: "Cursor", count: 7 },
  ],
};

function read(segments: EyebrowToken[][]) {
  return segments.map((segment) => segment.map((t) => (t.kind === "text" ? t.text : t.value)).join("")).join(" · ");
}

describe("changesEyebrow", () => {
  it("reads the frame for everyone", () => {
    expect(read(changesEyebrow(COUNTS, null))).toBe("53 changes this week · 41 by agents · 9 by people · 3 by qbrix · 2 undone");
  });

  it("counts per client with agents selected", () => {
    const narrowed = { ...COUNTS, total: 41, undone: 1 };
    expect(read(changesEyebrow(narrowed, "connection"))).toBe(
      "41 changes by agents this week · Claude Code 34 · Cursor 7 · 1 undone",
    );
  });

  it("names people and qbrix without clients", () => {
    expect(read(changesEyebrow({ ...COUNTS, total: 1, undone: 0 }, "member"))).toBe("1 change by people this week · 0 undone");
    expect(read(changesEyebrow({ ...COUNTS, total: 3, undone: 0 }, "qbrix"))).toBe("3 changes by qbrix this week · 0 undone");
  });

  it("leads with a counter, which the frozen eyebrow keeps", () => {
    expect(changesEyebrow(COUNTS, "qbrix")[0][0].kind).toBe("counter");
  });
});

describe("whoCounts", () => {
  it("makes everyone the sum of who, whatever total says", () => {
    expect(whoCounts({ ...COUNTS, total: 41 }).everyone).toBe(53);
  });

  it("has no numbers before the counts arrive", () => {
    expect(whoCounts(undefined).everyone).toBeUndefined();
  });
});
