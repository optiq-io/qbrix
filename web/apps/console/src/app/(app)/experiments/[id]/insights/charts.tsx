"use client";

import { vizSeries, vizSeriesDim } from "@qbrix/ui/components/belief-viz";
import { cn } from "@qbrix/ui/lib/utils";

// the board's charts are flex rectangles, not plotted SVG — grouped bars,
// progress rows and stacked columns. that is why this tab drops recharts
// entirely, and why nothing here needs an SVG gradient: the `area-chart`
// gradient-id trap (an id built from `color.replace("#","")`, which breaks the
// moment a colour is `var(--color-viz-N)`) has no way to reappear.
//
// geometry is the only thing that goes through inline `style` — percentages
// tailwind cannot emit at runtime. every colour is a viz token class.

export function ChartPanel({
  title,
  note,
  legend,
  children,
}: {
  title: string;
  note?: string;
  legend?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-4 rounded-[14px] border border-border-subtle bg-bg-raised p-5">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-[15px] font-medium text-text-primary">{title}</h3>
        {note && <span className="text-[13px] text-text-faint">{note}</span>}
      </div>
      {legend}
      {children}
    </div>
  );
}

export function ChartEmpty({ height }: { height: number }) {
  return (
    <div
      className="flex items-center justify-center text-[13px] text-text-faint"
      style={{ height }}
    >
      No data in this range
    </div>
  );
}

export function Legend({
  items,
}: {
  items: { label: string; index: number }[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-5">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-2">
          <span
            className={cn("size-2.5 rounded-[3px]", vizSeries(item.index))}
          />
          <span className="text-[13px] text-text-dim">{item.label}</span>
        </span>
      ))}
    </div>
  );
}

// show roughly six x labels however many buckets there are — at 30d/12h that
// is 60 columns and every label would collide
function labelStride(count: number): number {
  return Math.max(1, Math.ceil(count / 6));
}

/** one accent bar per bucket, baseline-aligned. */
export function BarSeries({
  points,
  height = 105,
}: {
  points: { key: string; value: number; label: string }[];
  height?: number;
}) {
  if (points.length === 0) return <ChartEmpty height={height + 21} />;

  const max = Math.max(...points.map((p) => p.value), 0);
  const stride = labelStride(points.length);

  return (
    <div className="flex items-end gap-1.5" style={{ height: height + 21 }}>
      {points.map((p, i) => (
        <div key={p.key} className="flex min-w-0 flex-1 flex-col gap-1.5">
          <div className="flex items-end justify-center" style={{ height }}>
            <div
              className="w-full rounded-t-[3px] bg-accent/75"
              style={{ height: max > 0 ? `${(p.value / max) * 100}%` : 0 }}
            />
          </div>
          <span className="overflow-visible whitespace-nowrap text-center text-[11.5px] text-text-faint">
            {i % stride === 0 ? p.label : " "}
          </span>
        </div>
      ))}
    </div>
  );
}

/** dot + name + value over a full-width track, each bar scaled to the largest.
 *  scaled to the max rather than to 1.0: reward rates cluster low (a few per
 *  cent), and against a 0–1 axis every bar would be an invisible sliver. */
export function RankedBars({
  rows,
  height = 159,
}: {
  rows: { index: number; name: string; value: number; display: string }[];
  height?: number;
}) {
  if (rows.length === 0) return <ChartEmpty height={height} />;

  const max = Math.max(...rows.map((r) => r.value), 0);

  return (
    <div
      className="flex flex-col justify-center gap-[18px]"
      style={{ minHeight: height }}
    >
      {rows.map((row) => (
        <div key={row.name} className="flex flex-col gap-[9px]">
          <div className="flex items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2">
              <span
                className={cn(
                  "size-2 shrink-0 rounded-full",
                  vizSeries(row.index),
                )}
              />
              <span className="truncate text-[14px] text-text-secondary">
                {row.name}
              </span>
            </span>
            <span className="shrink-0 text-[14px] text-text-primary">
              {row.display}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden bg-white/[0.04]">
            <div
              className={cn("h-full", vizSeries(row.index))}
              style={{ width: max > 0 ? `${(row.value / max) * 100}%` : 0 }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export type StackPoint = {
  key: string;
  label: string;
  segments: { index: number; name: string; value: number }[];
};

/** 100%-stacked columns: each segment is a 2px full-colour cap over a body at
 *  the palette's `-dim` step, per the board. */
export function StackedColumns({
  points,
  height = 159,
}: {
  points: StackPoint[];
  height?: number;
}) {
  if (points.length === 0) return <ChartEmpty height={height + 21} />;

  const stride = labelStride(points.length);

  return (
    <div className="flex items-end gap-px" style={{ height: height + 21 }}>
      {points.map((p, i) => {
        const total = p.segments.reduce((sum, s) => sum + s.value, 0);
        return (
          <div key={p.key} className="flex min-w-0 flex-1 flex-col gap-1.5">
            <div className="flex flex-col justify-end" style={{ height }}>
              {total > 0 &&
                p.segments.map((s) => (
                  <div
                    key={s.index}
                    className="flex w-full flex-col"
                    style={{ height: `${(s.value / total) * 100}%` }}
                    title={`${s.name}: ${s.value}`}
                  >
                    <div className={cn("h-[2px] shrink-0", vizSeries(s.index))} />
                    <div className={cn("min-h-0 flex-1", vizSeriesDim(s.index))} />
                  </div>
                ))}
            </div>
            <span className="overflow-visible whitespace-nowrap text-center text-[11.5px] text-text-faint">
              {i % stride === 0 ? p.label : " "}
            </span>
          </div>
        );
      })}
    </div>
  );
}
