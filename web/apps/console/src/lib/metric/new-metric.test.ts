import { describe, expect, it } from "vitest";
import { metricErrorField, NEW_METRIC, parseWindow, usedBy, validateMetric } from "./new-metric";

const METRIC = { ...NEW_METRIC, name: "order_value", semantic: "Total paid for the order", window: "7 days" };

describe("parseWindow", () => {
  it.each([
    ["7 days", 604_800],
    ["24 hours", 86_400],
    ["1 hour", 3_600],
    ["90 minutes", 5_400],
    ["2w", 1_209_600],
    [" 30 S ", 30],
  ])("reads %s", (text, seconds) => {
    expect(parseWindow(text)).toBe(seconds);
  });

  it.each(["", "7", "days", "0 days", "-1 day", "7 fortnights", "1.5 hours"])("refuses %j", (text) => {
    expect(parseWindow(text)).toBeNull();
  });
});

describe("validateMetric", () => {
  it("builds the body, with no range but a score's", () => {
    expect(validateMetric({ ...METRIC, lo: "1", hi: "5" }).body).toEqual({
      name: "order_value",
      semantic: "Total paid for the order",
      type: "conversion",
      range: null,
      window_seconds: 604_800,
    });
    expect(validateMetric({ ...METRIC, type: "score", lo: "1", hi: "5" }).body?.range).toEqual({ lo: 1, hi: 5 });
  });

  it("names each problem on its field", () => {
    expect(validateMetric(NEW_METRIC).errors).toMatchObject({ name: expect.any(String), semantic: expect.any(String) });
    expect(validateMetric({ ...METRIC, name: "Order Value" }).errors?.name).toContain("lowercase");
    expect(validateMetric({ ...METRIC, window: "soon" }).errors?.window).toBeDefined();
  });

  it.each([
    ["", ""],
    ["5", "1"],
    ["1", "1"],
    ["a", "5"],
  ])("refuses a score from %j to %j", (lo, hi) => {
    expect(validateMetric({ ...METRIC, type: "score", lo, hi }).errors?.range).toBeDefined();
  });
});

describe("usedBy", () => {
  it("says who else uses it", () => {
    const loop = { id: "1", key: "a", name: "Search ranking", state: "live" as const };
    expect(usedBy({ loops: [] })).toBe("no other loop yet");
    expect(usedBy({ loops: [loop] })).toBe("Search ranking");
    expect(usedBy({ loops: [loop, loop] })).toBe("2 other loops");
  });
});

describe("metricErrorField", () => {
  it.each([
    ["METRIC_NAME_TAKEN", "a metric named 'x' already exists", "name"],
    ["INVALID_METRIC", "a metric name is what code sends", "name"],
    ["INVALID_METRIC", "a metric needs a semantic: what it stands for", "semantic"],
    ["INVALID_METRIC", "a window is a positive number of seconds, got 0", "window"],
    ["INVALID_METRIC", "a score range needs lo below hi, got [5.0, 1.0]", "range"],
  ])("%s %s goes on %s", (code, detail, field) => {
    expect(metricErrorField({ code, detail })?.field).toBe(field);
  });

  it("leaves the rest to the toast", () => {
    expect(metricErrorField({ code: "INVALID_METRIC", detail: "unknown metric type 'x'" })).toBeNull();
    expect(metricErrorField({ detail: "request failed" })).toBeNull();
  });
});
