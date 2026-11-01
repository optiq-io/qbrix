import { describe, expect, it } from "vitest";
import { wireCalls } from "./wire";

describe("wireCalls", () => {
  it("pairs select with outcome for a metric reported per decision", () => {
    expect(wireCalls({ loopKey: "checkout-headline", metricKind: "outcome" })).toEqual([
      'select("checkout-headline", ctx)',
      "outcome(request_id, 1)",
    ]);
  });

  it("pairs select with track for a metric reported as an event", () => {
    expect(wireCalls({ loopKey: "checkout-headline", metricKind: "track", eventName: "checkout_completed" })).toEqual([
      'select("checkout-headline", ctx)',
      'track("checkout_completed", 1)',
    ]);
  });
});
