export type ShareOption = { key: string; name: string };

/** decisions per option, in the order of the options */
export type ShareColumn = { at: number; decisions: number[] };

/** rank 0 is the leading option, rank 3 the "others" band */
export type ShareBand = {
  key: string;
  name: string;
  rank: 0 | 1 | 2 | 3;
  /** the options this band draws: one, or several for "others" */
  members: number[];
};

export type ShareSegment = { rank: ShareBand["rank"]; y: number; height: number };
export type ShareRect = { at: number; x: number; width: number; segments: ShareSegment[] };

const TOP_OPTIONS = 3;
const BAND_GAP = 1;

export function mergeColumns(columns: ShareColumn[], step: number): ShareColumn[] {
  const merged = new Map<number, number[]>();
  for (const { at, decisions } of columns) {
    const bucket = Math.floor(at / step) * step;
    const sum = merged.get(bucket);
    if (sum) decisions.forEach((value, index) => (sum[index] = (sum[index] ?? 0) + value));
    else merged.set(bucket, [...decisions]);
  }
  return [...merged.entries()].sort(([a], [b]) => a - b).map(([at, decisions]) => ({ at, decisions }));
}

/** the three largest options in the columns shown keep their tones and the rest
    are one "others" band, so a pin or a poll never recolours within one view */
export function rankBands(options: ShareOption[], columns: ShareColumn[]): ShareBand[] {
  const totals = options.map((_, index) => columns.reduce((sum, column) => sum + (column.decisions[index] ?? 0), 0));
  const ranked = options.map((_, index) => index).sort((a, b) => totals[b] - totals[a] || a - b);

  if (options.length <= TOP_OPTIONS) {
    return ranked.map((index, rank) => ({
      key: options[index].key,
      name: options[index].name,
      rank: rank as ShareBand["rank"],
      members: [index],
    }));
  }
  return [
    ...ranked.slice(0, TOP_OPTIONS).map((index, rank) => ({
      key: options[index].key,
      name: options[index].name,
      rank: rank as ShareBand["rank"],
      members: [index],
    })),
    { key: "others", name: "others", rank: 3 as const, members: ranked.slice(TOP_OPTIONS) },
  ];
}

export function columnTotal(column: ShareColumn): number {
  return column.decisions.reduce((sum, value) => sum + value, 0);
}

/** each band's share of a column, or null for a column with no decisions */
export function bandShares(column: ShareColumn, bands: ShareBand[]): number[] | null {
  const total = columnTotal(column);
  if (total === 0) return null;
  return bands.map((band) => band.members.reduce((sum, index) => sum + (column.decisions[index] ?? 0), 0) / total);
}

/** the columns as rects, the leading option at the bottom */
export function columnRects(
  columns: ShareColumn[],
  bands: ShareBand[],
  width: number,
  height: number,
  gap: number,
): ShareRect[] {
  const count = columns.length;
  if (count === 0) return [];
  const columnWidth = (width - gap * (count - 1)) / count;

  return columns.map((column, index) => {
    const shares = bandShares(column, bands);
    const segments: ShareSegment[] = [];
    if (shares) {
      const drawn = shares.filter((share) => share > 0).length;
      const usable = height - BAND_GAP * Math.max(0, drawn - 1);
      let bottom = height;
      bands.forEach((band, at) => {
        if (shares[at] <= 0) return;
        const bandHeight = shares[at] * usable;
        segments.push({ rank: band.rank, y: bottom - bandHeight, height: bandHeight });
        bottom -= bandHeight + BAND_GAP;
      });
    }
    return { at: column.at, x: index * (columnWidth + gap), width: columnWidth, segments };
  });
}

const lerp = (from: number, to: number, t: number) => from + (to - from) * t;

/** the old columns on their way into the columns they merge into. every old
    column ends on its target's exact rect, so the swap at t = 1 doesn't show */
export function mergeTween(from: ShareRect[], to: ShareRect[], step: number, t: number): ShareRect[] {
  const targets = new Map(to.map((rect) => [rect.at, rect]));
  const merging = new Set(from.map((rect) => Math.floor(rect.at / step) * step));
  const arriving = to.filter((rect) => !merging.has(rect.at));
  const moving = from.flatMap((rect) => {
    const target = targets.get(Math.floor(rect.at / step) * step);
    if (!target) return [];
    return [
      {
        at: rect.at,
        x: lerp(rect.x, target.x, t),
        width: lerp(rect.width, target.width, t),
        segments: target.segments.map((end) => {
          const start = rect.segments.find((segment) => segment.rank === end.rank);
          return {
            rank: end.rank,
            y: lerp(start?.y ?? end.y + end.height, end.y, t),
            height: lerp(start?.height ?? 0, end.height, t),
          };
        }),
      },
    ];
  });
  return [...moving, ...arriving];
}
