import { describe, expect, it } from "vitest";
import { axisLabels, columnCount, pickInterval } from "./interval";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const START = Date.UTC(2026, 9, 3);

describe("pickInterval", () => {
  it.each([
    ["20 minutes", 20 * MINUTE, MINUTE, 20],
    ["9 hours", 9 * HOUR, 15 * MINUTE, 36],
    ["day 12", 12 * DAY, 6 * HOUR, 48],
    ["day 40", 40 * DAY, DAY, 40],
  ])("matches the board at %s", (_, span, step, columns) => {
    expect(pickInterval(START, START + span)).toBe(step);
    expect(columnCount(START, START + span, step)).toBe(columns);
  });

  it("restarts at one minute for a new cycle", () => {
    expect(pickInterval(START, START)).toBe(MINUTE);
    expect(pickInterval(START, START + 30_000)).toBe(MINUTE);
  });

  it("gives the fixed windows their own steps", () => {
    expect(pickInterval(START, START + DAY)).toBe(30 * MINUTE);
    expect(pickInterval(START, START + 7 * DAY)).toBe(6 * HOUR);
  });

  it("moves up exactly when the span outgrows 48 columns", () => {
    expect(pickInterval(START, START + 48 * MINUTE)).toBe(MINUTE);
    expect(pickInterval(START, START + 48 * MINUTE + 1)).toBe(5 * MINUTE);
  });

  it("stays on the last step past the end of the ladder", () => {
    expect(pickInterval(START, START + 90 * DAY)).toBe(DAY);
  });

  it("only ever moves to a step the last one divides, so columns can merge", () => {
    let last = pickInterval(START, START + MINUTE);
    for (let span = MINUTE; span <= 40 * DAY; span += 7 * MINUTE) {
      const step = pickInterval(START, START + span);
      expect(step % last).toBe(0);
      last = step;
    }
  });
});

describe("axisLabels", () => {
  const local = (month: number, day: number, hour = 0, minute = 0) => new Date(2026, month, day, hour, minute).getTime();
  const words = (since: number, until: number) => axisLabels(since, until).map(({ label }) => label);

  it("matches the board's four examples", () => {
    expect(words(local(9, 3, 14), local(9, 3, 14, 20))).toEqual(["14:00", "14:10", "now"]);
    expect(words(local(9, 3, 14), local(9, 3, 23))).toEqual(["14:00", "18:00", "22:00", "now"]);
    expect(words(local(9, 3), local(9, 15))).toEqual(["3 Oct", "6 Oct", "9 Oct", "12 Oct", "now"]);
    expect(words(local(9, 3), local(10, 12))).toEqual(["3 Oct", "13 Oct", "23 Oct", "2 Nov", "now"]);
  });

  it("names the day once it changes", () => {
    expect(words(local(9, 3, 18), local(9, 4, 18))).toContain("4 Oct 00:00");
  });

  it("never shows more than five labels at any age", () => {
    for (let span = MINUTE; span <= 200 * DAY; span = Math.ceil(span * 1.3)) {
      expect(axisLabels(START, START + span).length).toBeLessThanOrEqual(5);
    }
  });
});
