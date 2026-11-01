import { describe, expect, it } from "vitest";
import type { LoopResults } from "@/lib/api/types";
import { loopStatus } from "./status";

const LIFT = { value: null, early: true, since: "", until: "" };

function results(sealed: number, lift: LoopResults["lift"]): LoopResults {
  return {
    lift,
    share: { options: [{ key: "a", name: "A", decisions: 5, share: 1, sealed, waiting: 5 - sealed }] },
  } as LoopResults;
}

describe("loopStatus", () => {
  it("warms up before the first window closes, even with conversions already sealed", () => {
    expect(loopStatus("live", results(3, null))).toBe("warming_up");
    expect(loopStatus("live", undefined)).toBe("warming_up");
  });

  it("warms up past the window while nothing has sealed", () => {
    expect(loopStatus("live", results(0, LIFT))).toBe("warming_up");
  });

  it("is live once the window has closed with a sealed decision", () => {
    expect(loopStatus("live", results(1, LIFT))).toBe("live");
  });

  it("leaves a draft and a paused loop as they are", () => {
    expect(loopStatus("draft", undefined)).toBe("draft");
    expect(loopStatus("paused", results(0, null))).toBe("paused");
  });
});
