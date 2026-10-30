const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

export const STEPS_MS = [
  MINUTE_MS,
  5 * MINUTE_MS,
  15 * MINUTE_MS,
  30 * MINUTE_MS,
  HOUR_MS,
  3 * HOUR_MS,
  6 * HOUR_MS,
  12 * HOUR_MS,
  DAY_MS,
];

export const MAX_COLUMNS = 48;

/** the smallest step on the ladder that keeps the span within 48 columns. the
    results api picks its step by the same rule (step_for in mod/loop/stat.py) */
export function pickInterval(cycleStart: number, now: number): number {
  const span = now - cycleStart;
  return STEPS_MS.find((step) => span <= step * MAX_COLUMNS) ?? STEPS_MS[STEPS_MS.length - 1];
}

/** the step-aligned columns that cover [since, until) */
export function columnCount(since: number, until: number, step: number): number {
  if (until <= since) return 0;
  return Math.floor((until - 1) / step) - Math.floor(since / step) + 1;
}

export type AxisLabel = { at: number; label: string };

const MAX_DATED_LABELS = 4;
const MIN_GAP = 0.1;
const TIME_INTERVALS_MIN = [1, 2, 10, 30, 60, 120, 240, 360, 720];
const DATE_INTERVALS_DAYS = [1, 3, 10, 30, 90];

const formatTime = (at: number) =>
  new Date(at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
const formatDate = (at: number) => new Date(at).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const dayOf = (at: number) => new Date(at).toDateString();

function timeMarks(since: number, until: number, minutes: number): number[] {
  const grain = Math.min(minutes, 60) * MINUTE_MS;
  const anchor = new Date(since);
  anchor.setSeconds(0, 0);
  anchor.setMinutes(Math.floor(anchor.getMinutes() / (grain / MINUTE_MS)) * (grain / MINUTE_MS));
  const marks: number[] = [];
  for (let at = anchor.getTime() + minutes * MINUTE_MS; at < until; at += minutes * MINUTE_MS) marks.push(at);
  return marks;
}

function dateMarks(since: number, until: number, days: number): number[] {
  const cursor = new Date(since);
  cursor.setHours(0, 0, 0, 0);
  const marks: number[] = [];
  for (cursor.setDate(cursor.getDate() + days); cursor.getTime() < until; cursor.setDate(cursor.getDate() + days)) {
    marks.push(cursor.getTime());
  }
  return marks;
}

/** the start, round values after it, then "now": five labels at most. minutes
    and hours show times, with the day once it changes; days show dates */
export function axisLabels(since: number, until: number): AxisLabel[] {
  const span = until - since;
  if (span <= 0) return [];

  const thin = (marks: number[]) => {
    const kept = [since];
    for (const at of marks) {
      if (at - kept[kept.length - 1] >= span * MIN_GAP && until - at >= span * MIN_GAP) kept.push(at);
    }
    return kept;
  };

  const candidates = [
    ...TIME_INTERVALS_MIN.map((minutes) => ({ dated: false, marks: thin(timeMarks(since, until, minutes)) })),
    ...DATE_INTERVALS_DAYS.map((days) => ({ dated: true, marks: thin(dateMarks(since, until, days)) })),
  ];
  const chosen =
    candidates.find(({ marks }) => marks.length <= MAX_DATED_LABELS) ?? candidates[candidates.length - 1];

  const labels = chosen.marks.map((at, index) => {
    if (chosen.dated) return { at, label: formatDate(at) };
    const changedDay = index > 0 && dayOf(at) !== dayOf(chosen.marks[index - 1]);
    return { at, label: changedDay ? `${formatDate(at)} ${formatTime(at)}` : formatTime(at) };
  });
  return [...labels, { at: until, label: "now" }];
}
