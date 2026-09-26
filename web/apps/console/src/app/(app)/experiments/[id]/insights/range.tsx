"use client";

import { cn } from "@qbrix/ui/lib/utils";

// board `APP · Experiment / Insights` / Title / Range: a four-segment pill,
// plus a bucket pill beside it.
//
// the board draws only the range, but dropping the bucket control the old page
// had was a real loss of capability, so it comes back — as a constrained set
// per range rather than the old free number + unit. that control could ask for
// 30d of 1-second buckets: 2.6M of them, which stalls the endpoint and then
// tries to render 2.6M nodes. the options below top out at 120 buckets, past
// which a stacked column is thinner than its own 2px caps and stops meaning
// anything.
//
// one interval drives every chart on the page, so a bucket means the same
// thing in all of them and reading across panels stays valid.

export type RangePreset = "24h" | "7d" | "14d" | "30d";

export const RANGE_PRESETS: RangePreset[] = ["24h", "7d", "14d", "30d"];

const MINUTE = 60_000;
const HOUR = 3_600_000;
const DAY = 24 * HOUR;

const DURATION: Record<RangePreset, number> = {
  "24h": DAY,
  "7d": 7 * DAY,
  "14d": 14 * DAY,
  "30d": 30 * DAY,
};

export type IntervalOption = { label: string; ms: number };

// bucket counts in comments — the reason each set stops where it does
export const INTERVALS: Record<RangePreset, IntervalOption[]> = {
  "24h": [
    { label: "15m", ms: 15 * MINUTE }, // 96
    { label: "30m", ms: 30 * MINUTE }, // 48
    { label: "1h", ms: HOUR }, // 24
  ],
  "7d": [
    { label: "3h", ms: 3 * HOUR }, // 56
    { label: "6h", ms: 6 * HOUR }, // 28
    { label: "12h", ms: 12 * HOUR }, // 14
  ],
  "14d": [
    { label: "6h", ms: 6 * HOUR }, // 56
    { label: "12h", ms: 12 * HOUR }, // 28
    { label: "1d", ms: DAY }, // 14
  ],
  "30d": [
    { label: "6h", ms: 6 * HOUR }, // 120
    { label: "12h", ms: 12 * HOUR }, // 60
    { label: "1d", ms: DAY }, // 30
  ],
};

/** the bucket a preset opens on — the density the board draws. */
export function defaultInterval(preset: RangePreset): number {
  return preset === "24h" ? HOUR : preset === "7d" ? 3 * HOUR : preset === "14d" ? 6 * HOUR : 12 * HOUR;
}

export type RangeParams = {
  start_ms: number;
  end_ms: number;
  interval_ms: number;
};

/** `now` is a parameter so the query key stays stable between renders — pass a
    value pinned in state, never `Date.now()` inline. */
export function rangeParams(
  preset: RangePreset,
  now: number,
  intervalMs: number,
): RangeParams {
  return {
    start_ms: now - DURATION[preset],
    end_ms: now,
    interval_ms: intervalMs,
  };
}

function Pill({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex h-9 shrink-0 items-center gap-0.5 rounded-[11px] bg-white/[0.04] p-[3px]"
    >
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={opt.key}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.key)}
            className={cn(
              "flex h-[30px] items-center rounded-[9px] px-3 text-[14px] transition-colors",
              active
                ? "bg-white/[0.08] font-medium text-text-primary"
                : "text-text-dim hover:text-text-secondary",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// the two controls are deliberately not adjacent. side by side they were two
// pills of time units with nothing to say which was the window and which the
// granularity — and they do not share a scope: the range drives the KPIs *and*
// the charts, the bucket only reshapes the three time-series charts. so the
// range lives in the page head and the bucket sits over the chart grid, where
// what it affects is what is under it.

/** page-scoped: drives every query. lives in the head. */
export function RangeControl({
  preset,
  onChange,
}: {
  preset: RangePreset;
  onChange: (next: RangePreset) => void;
}) {
  return (
    <Pill
      label="Time range"
      options={RANGE_PRESETS.map((p) => ({ key: p, label: p }))}
      value={preset}
      onChange={(k) => onChange(k as RangePreset)}
    />
  );
}

/** chart-scoped: only the time-series panels re-bucket. lives over the grid. */
export function BucketControl({
  preset,
  intervalMs,
  onChange,
}: {
  preset: RangePreset;
  intervalMs: number;
  onChange: (ms: number) => void;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-[13px] text-text-dim">Bucket</span>
      <Pill
        label="Bucket size"
        options={INTERVALS[preset].map((o) => ({
          key: String(o.ms),
          label: o.label,
        }))}
        value={String(intervalMs)}
        onChange={(k) => onChange(Number(k))}
      />
    </div>
  );
}
