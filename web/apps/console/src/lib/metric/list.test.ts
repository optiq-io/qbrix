import { describe, expect, it } from "vitest";
import type { Metric } from "@/lib/api/types";
import { metricLine, metricsCounters } from "./list";

const METRIC: Metric = {
  id: "m1",
  name: "checkout_completed",
  type: "conversion",
  range: null,
  version: "1.0",
  semantic: "Payment confirmed on the payment sheet",
  window_seconds: 86_400,
  loops: [],
};

describe("metricLine", () => {
  it("reads type, window and version", () => {
    expect(metricLine(METRIC)).toBe("Conversion · 24 hours · version 1.0");
  });

  it("names a window over a day in days", () => {
    expect(metricLine({ ...METRIC, type: "value", window_seconds: 604_800, version: "1.2" })).toBe(
      "Value · 7 days · version 1.2",
    );
  });
});

describe("metricsCounters", () => {
  const now = Date.parse("2026-11-04T12:00:00Z");

  it("counts the metrics and says when the list was read", () => {
    expect(metricsCounters([METRIC, METRIC], now - 40_000, now)).toEqual({ count: "2", updated: "40 seconds ago" });
  });

  it("leaves updated out before the first read", () => {
    expect(metricsCounters([], 0, now)).toEqual({ count: "0", updated: undefined });
  });
});
