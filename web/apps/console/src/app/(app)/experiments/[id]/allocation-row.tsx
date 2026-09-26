"use client";

import { DataRow, Cell } from "@qbrix/ui/components/data-table";
import { BeliefViz, vizSeries } from "@qbrix/ui/components/belief-viz";
import { observedRange } from "@qbrix/ui/lib/observed-range";
import { cn } from "@qbrix/ui/lib/utils";
import type { ArmStats } from "@/lib/api/types";
import { pct, num } from "./format";

// one row of the Traffic allocation table, board `APP · Experiment / Overview`.
// column widths here must match the `columns` array on the Overview page — the
// bar and the cells are aligned by agreeing on those numbers, nothing enforces
// it at the type level.
export function AllocationRow({
  arm,
  share,
  isLeader,
  domain,
}: {
  arm: ArmStats;
  share: number;
  isLeader: boolean;
  /** shared x-domain for the belief column, computed once for the whole table */
  domain?: [number, number];
}) {
  const feedback = arm.feedback_count ?? 0;
  const range = arm.avg_reward !== null ? observedRange(arm.avg_reward, feedback) : null;
  const series = arm.arm_index;

  return (
    <DataRow height={72} className={isLeader ? "bg-accent/[0.03]" : undefined}>
      <Cell>
        <div className="flex items-center gap-[13px]">
          <span className={cn("size-[9px] shrink-0 rounded-full", vizSeries(series))} />
          <div className="flex min-w-0 flex-col gap-1">
            <span className="truncate text-[15px] font-medium text-text-primary">
              {arm.arm_name}
            </span>
            <span className="truncate text-[13px] text-text-faint">
              {isLeader ? "leading · " : ""}n={num(feedback)}
            </span>
          </div>
        </div>
      </Cell>

      <Cell width={170}>
        <BeliefViz
          mean={arm.avg_reward}
          count={feedback}
          series={series}
          domain={domain}
        />
      </Cell>

      <Cell width={240}>
        <div className="h-2.5 w-full overflow-hidden bg-white/[0.04]">
          <div
            className={cn(
              "h-full transition-[width] duration-[var(--motion-data)] ease-entrance",
              vizSeries(series),
            )}
            style={{ width: `${share * 100}%` }}
          />
        </div>
      </Cell>

      <Cell width={72} align="right">
        <span
          className={cn(
            "font-mono text-[15px] tracking-[0.3px]",
            isLeader ? "text-accent" : "text-text-secondary",
          )}
        >
          {pct(share)}
        </span>
      </Cell>

      <Cell width={78} align="right">
        <span className="font-mono text-[15px] tracking-[0.3px] text-text-primary">
          {arm.avg_reward !== null ? pct(arm.avg_reward, 2) : "—"}
        </span>
      </Cell>

      <Cell width={96} align="right">
        <span className="font-mono text-[13px] tracking-[0.3px] text-text-dim">
          {range
            ? `${(range.lo * 100).toFixed(2)} – ${pct(range.hi, 2)}`
            : "—"}
        </span>
      </Cell>
    </DataRow>
  );
}
