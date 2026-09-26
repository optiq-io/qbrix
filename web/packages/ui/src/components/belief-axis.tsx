import { cn } from "../lib/utils";

// board `APP · Experiment / Arms` / Axis — the tick rail under the belief
// column. it is what makes the curves comparable: without a labelled axis a
// density shape says "roughly here", with one it says "6.4%".
//
// the rail is positioned by the caller to sit under the BELIEF column, and its
// ticks must come from the same `snapDomain` call that produced the curves'
// domain — a rail drawn over a different domain is worse than none.
export function BeliefAxis({
  ticks,
  domain,
  width,
  format,
  className,
}: {
  ticks: number[];
  domain: [number, number];
  width: number;
  format: (v: number) => string;
  className?: string;
}) {
  const [lo, hi] = domain;
  const span = hi - lo;

  return (
    <div className={cn("relative h-4 shrink-0", className)} style={{ width }}>
      {ticks.map((t) => {
        const pos = span > 0 ? ((t - lo) / span) * 100 : 0;
        return (
          <span
            key={t}
            className="absolute top-0 -translate-x-1/2 whitespace-nowrap font-mono text-[11px] text-text-faint"
            style={{ left: `${pos}%` }}
          >
            {format(t)}
          </span>
        );
      })}
    </div>
  );
}
