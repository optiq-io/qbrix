// the insight API returns only a mean and a count per arm — no variance, no
// posterior. a Wilson score interval is the one range derivable from that pair,
// which is exactly what the boards' method note claims it is: "derived from
// selection and feedback counts, not the learner's posterior".
//
// it treats the mean as a proportion, so it assumes reward ∈ [0,1]. that holds
// for BINARY and BOUNDED rewards; a CONTINUOUS reward outside that range is
// clamped rather than silently producing a nonsense interval. the API exposes
// no reward type, so this assumption cannot be checked here — it is the same
// one the boards make by rendering avg_reward as a percentage.

const Z = 1.96; // 95%

export type Range = { lo: number; hi: number };

export function observedRange(mean: number, count: number): Range | null {
  if (!Number.isFinite(mean) || count <= 0) return null;

  const p = Math.min(1, Math.max(0, mean));
  const z2 = Z * Z;
  const denom = 1 + z2 / count;
  const center = (p + z2 / (2 * count)) / denom;
  const margin =
    (Z / denom) * Math.sqrt((p * (1 - p)) / count + z2 / (4 * count * count));

  return {
    lo: Math.max(0, center - margin),
    hi: Math.min(1, center + margin),
  };
}

// the x-domain the belief curves are drawn over.
//
// plotting them over the full [0,1] is what the board appears to do, but the
// board's example sits near 65% — at a realistic 3–6% conversion rate every
// curve collapses into the leftmost two buckets and the column says nothing.
// so the domain is the union of the arms' observed ranges, padded.
//
// it must be **shared by every row**: comparing belief shapes across arms is
// only meaningful on a common axis, and a per-row domain would make a confident
// arm and a vague one look identical.
export function beliefDomain(
  arms: { mean: number | null; count: number }[],
): [number, number] {
  const ranges = arms
    .map((a) => (a.mean === null ? null : observedRange(a.mean, a.count)))
    .filter((r): r is Range => r !== null);

  if (ranges.length === 0) return [0, 1];

  const lo = Math.min(...ranges.map((r) => r.lo));
  const hi = Math.max(...ranges.map((r) => r.hi));
  const pad = Math.max((hi - lo) * 0.15, 0.002);

  return [Math.max(0, lo - pad), Math.min(1, hi + pad)];
}

// round a domain outward to a readable tick step, for the surfaces that draw an
// axis under the curves (Arms). the Arms board's ticks are 0/2/4/6/8/10% —
// round numbers, which `beliefDomain` alone will not produce.
//
// deliberately *not* applied on Overview: it has no axis, so snapping would
// only widen the domain and undo the separation the tight fit buys.
export function snapDomain(
  [lo, hi]: [number, number],
  targetTicks = 5,
): { domain: [number, number]; ticks: number[] } {
  const span = hi - lo;
  if (!(span > 0)) return { domain: [0, 1], ticks: [0, 0.5, 1] };

  const raw = span / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;

  const start = Math.max(0, Math.floor(lo / step) * step);
  const end = Math.min(1, Math.ceil(hi / step) * step);

  const ticks: number[] = [];
  // accumulate off the index, not by repeated addition — floating-point drift
  // over ~10 steps is enough to produce a 5.999999% label
  for (let i = 0; start + i * step <= end + step / 1e6; i++) {
    ticks.push(start + i * step);
  }

  return { domain: [start, end], ticks };
}
