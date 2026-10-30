import { describe, expect, it } from "vitest";
import { pickInterval } from "./interval";
import { bandShares, columnRects, mergeColumns, mergeTween, rankBands, type ShareColumn, type ShareOption } from "./share";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const START = Date.UTC(2026, 9, 3);

const optionsOf = (count: number): ShareOption[] =>
  Array.from({ length: count }, (_, index) => ({ key: `o${index}`, name: `Option ${index}` }));

function minutes(span: number): ShareColumn[] {
  return Array.from({ length: span / MINUTE }, (_, index) => ({
    at: START + index * MINUTE,
    decisions: [5 + (index % 7), 3 + (index % 3), 1 + (index % 2)],
  }));
}

const totals = (columns: ShareColumn[]) =>
  columns.reduce((sum, column) => sum.map((value, index) => value + column.decisions[index]), [0, 0, 0]);

describe("rankBands", () => {
  const column = (decisions: number[]): ShareColumn => ({ at: START, decisions });

  it("draws three tones and others for five options", () => {
    const bands = rankBands(optionsOf(5), [column([1, 40, 3, 30, 20])]);
    expect(bands.map(({ key }) => key)).toEqual(["o1", "o3", "o4", "others"]);
    expect(bands.map(({ rank }) => rank)).toEqual([0, 1, 2, 3]);
    expect(bands[3].members).toEqual([2, 0]);
  });

  it("draws no others band for three options", () => {
    const bands = rankBands(optionsOf(3), [column([10, 30, 20])]);
    expect(bands.map(({ key }) => key)).toEqual(["o1", "o2", "o0"]);
  });

  it("ranks over the whole range, so one column can't recolour an option", () => {
    const options = optionsOf(3);
    const earlier = [column([80, 30, 20])];
    const flipped = column([1, 30, 20]);
    expect(rankBands(options, [...earlier, flipped]).map(({ key }) => key)).toEqual(["o0", "o1", "o2"]);
  });

  it("merges others' shares into one band", () => {
    const bands = rankBands(optionsOf(5), [column([1, 40, 3, 30, 26])]);
    expect(bandShares(column([1, 40, 3, 30, 26]), bands)).toEqual([0.4, 0.3, 0.26, 0.04]);
  });

  it("has no share for a column with no decisions", () => {
    expect(bandShares(column([0, 0, 0]), rankBands(optionsOf(3), []))).toBeNull();
  });
});

describe("growing a cycle from 20 minutes to 40 days", () => {
  const raw = minutes(40 * DAY);
  const spans = [20, 60, 240, 540, 1440, 4320, 17280, 57600].map((count) => count * MINUTE);

  it("stays within 48 columns and never changes the option totals", () => {
    for (const span of spans) {
      const shown = raw.slice(0, span / MINUTE);
      const merged = mergeColumns(shown, pickInterval(START, START + span));
      expect(merged.length).toBeLessThanOrEqual(48);
      expect(totals(merged)).toEqual(totals(shown));
    }
  });

  it("merges onto the same columns however it gets there", () => {
    const direct = mergeColumns(raw, DAY);
    const stepwise = [5, 15, 30, 60, 180, 360, 720, 1440].reduce(
      (columns, step) => mergeColumns(columns, step * MINUTE),
      raw,
    );
    expect(stepwise).toEqual(direct);
  });
});

describe("mergeTween", () => {
  const options = optionsOf(3);
  const fine = minutes(49 * MINUTE);
  const step = 5 * MINUTE;
  const coarse = mergeColumns(fine, step);
  const bands = rankBands(options, coarse);
  const from = columnRects(fine, bands, 700, 132, 2);
  const to = columnRects(coarse, bands, 700, 132, 2);

  it("starts where the old columns are", () => {
    mergeTween(from, to, step, 0).forEach((rect, index) => {
      expect(rect.x).toBeCloseTo(from[index].x);
      expect(rect.width).toBeCloseTo(from[index].width);
      expect(rect.segments[0].height).toBeCloseTo(from[index].segments[0].height);
    });
  });

  it("ends with every old column exactly on the column it merged into", () => {
    for (const rect of mergeTween(from, to, step, 1)) {
      const target = to.find(({ at }) => at === Math.floor(rect.at / step) * step)!;
      expect(rect.x).toBeCloseTo(target.x);
      expect(rect.width).toBeCloseTo(target.width);
      expect(rect.segments).toEqual(target.segments);
    }
  });
});

describe("mergeTween with columns that arrived during the merge", () => {
  it("draws them where they will end up, so the right edge is never blank", () => {
    const options = optionsOf(3);
    const step = 5 * MINUTE;
    const fine = minutes(49 * MINUTE);
    const coarse = mergeColumns(minutes(60 * MINUTE), step);
    const bands = rankBands(options, coarse);
    const to = columnRects(coarse, bands, 700, 132, 2);
    const drawn = mergeTween(columnRects(fine, bands, 700, 132, 2), to, step, 0.5);
    expect(drawn[drawn.length - 1]).toEqual(to[to.length - 1]);
  });
});

describe("columnRects", () => {
  it("puts the leading option at the bottom and fills the height", () => {
    const columns = [{ at: START, decisions: [58, 29, 13] }];
    const [rect] = columnRects(columns, rankBands(optionsOf(3), columns), 100, 132, 2);
    expect(rect.segments.map(({ rank }) => rank)).toEqual([0, 1, 2]);
    expect(rect.segments[0].y + rect.segments[0].height).toBeCloseTo(132);
    expect(rect.segments[2].y).toBeCloseTo(0);
  });

  it("draws nothing for a column with no decisions", () => {
    const columns = [{ at: START, decisions: [0, 0, 0] }];
    const [rect] = columnRects(columns, rankBands(optionsOf(3), columns), 100, 132, 2);
    expect(rect.segments).toEqual([]);
  });
});
