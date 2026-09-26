import { cn } from "../lib/utils";

// board `APP · Experiment / Overview` → allocation table, BELIEF column: a
// 34-bucket density shape, bars bottom-aligned in a 36px box at gap 1
// (34 × 4px + 33 × 1px = 169 ≈ the drawn 170).
//
// the curve is a Beta density fitted to the *observed* counts — α = mean·n + 1,
// β = (1−mean)·n + 1 — not the learner's posterior, which no endpoint exposes.
// see `observed-range.ts` for the same reward ∈ [0,1] assumption and why it is
// the only shape derivable from what the API returns.
//
// a flat bar means "no feedback yet", which is honest: with n = 0 the fit is
// Beta(1,1), the uniform distribution.

const DEFAULT_BUCKETS = 34;

// tailwind never emits a composed class name, so the series colours are literal
export const VIZ_SERIES = [
  "bg-viz-1",
  "bg-viz-2",
  "bg-viz-3",
  "bg-viz-4",
  "bg-viz-5",
  "bg-viz-6",
] as const;

// the stacked-area fill under each series cap. the boards draw it at 24%; the
// palette publishes `-dim` at 20% for exactly this job, and a token beats a
// hand-picked alpha — see the viz block in globals.css.
export const VIZ_SERIES_DIM = [
  "bg-viz-1-dim",
  "bg-viz-2-dim",
  "bg-viz-3-dim",
  "bg-viz-4-dim",
  "bg-viz-5-dim",
  "bg-viz-6-dim",
] as const;

export function vizSeries(index: number): string {
  return VIZ_SERIES[index % VIZ_SERIES.length];
}

export function vizSeriesDim(index: number): string {
  return VIZ_SERIES_DIM[index % VIZ_SERIES_DIM.length];
}

function density(
  mean: number,
  count: number,
  domain: [number, number],
  BUCKETS: number,
): number[] {
  const p = Math.min(1, Math.max(0, mean));
  const n = Math.max(0, count);
  const a = p * n + 1;
  const b = (1 - p) * n + 1;

  const [d0, d1] = domain[1] > domain[0] ? domain : [0, 1];
  const span = d1 - d0;

  // log-space: α and β reach the thousands on a mature arm and x^(α−1)
  // overflows to Infinity long before that
  const logs = Array.from({ length: BUCKETS }, (_, i) => {
    const x = d0 + ((i + 0.5) / BUCKETS) * span;
    if (x <= 0 || x >= 1) return -Infinity;
    return (a - 1) * Math.log(x) + (b - 1) * Math.log(1 - x);
  });

  const peak = Math.max(...logs);
  if (!Number.isFinite(peak)) return logs.map(() => 0);
  return logs.map((l) => (Number.isFinite(l) ? Math.exp(l - peak) : 0));
}

export function BeliefViz({
  mean,
  count,
  series = 0,
  domain = [0, 1],
  buckets = DEFAULT_BUCKETS,
  width = 170,
  height = 36,
  className,
}: {
  mean: number | null;
  count: number;
  series?: number;
  /** shared across every row of a table — see `beliefDomain` */
  domain?: [number, number];
  /** Overview draws 34 in a 170px box; Arms draws 52 in 320px */
  buckets?: number;
  width?: number;
  height?: number;
  className?: string;
}) {
  const shape = density(mean ?? 0, mean === null ? 0 : count, domain, buckets);
  const tone = vizSeries(series);

  return (
    <div
      className={cn("flex items-end gap-px", className)}
      style={{ width, height }}
      aria-hidden
    >
      {shape.map((v, i) => (
        <span
          key={i}
          className={cn("min-w-0 flex-1 rounded-[1px]", tone)}
          style={{ height: Math.max(1, Math.round(v * height)) }}
        />
      ))}
    </div>
  );
}
