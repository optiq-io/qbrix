"use client";

import { format } from "date-fns";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { useSelectionUsage } from "@/ee/lib/billing/hooks";
import { formatMoney } from "@/ee/lib/billing/format";

function compact(n: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
}

function periodLabel(start: Date | null, end: Date | null): string {
  if (!start || !end) return "current period";
  return `${format(start, "d MMM")} – ${format(end, "d MMM")}`;
}

export function UsageMeter() {
  const { data: usage, isLoading } = useSelectionUsage();

  if (isLoading) return <Skeleton className="h-[72px] w-full" />;
  if (!usage) return null;

  const { used, included, overage, capped } = usage;
  const pct =
    included === null || included === 0
      ? 0
      : Math.min(100, (used / included) * 100);
  const remaining = included === null ? null : Math.max(0, included - used);

  // a paid tier passing its included volume bills overage; a free one is
  // refused, which is a different thing and reads differently
  const barColor = capped ? "bg-danger" : pct >= 80 ? "bg-amber" : "bg-accent";

  let footnote: string | null = null;
  if (capped) {
    footnote =
      "Included volume used — further selections are rejected until the period resets.";
  } else if (overage !== null && overage > 0) {
    footnote = `${compact(overage)} over included · ${formatMoney(
      usage.overageCost ?? 0,
      usage.currency ?? "eur",
    )}`;
  } else if (remaining !== null) {
    footnote = `${compact(remaining)} included selections left`;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <div className="flex items-baseline gap-2">
          <span className="text-[22px] font-semibold tracking-[-0.4px] tabular-nums text-text-primary">
            {compact(used)}
          </span>
          <span className="text-[14px] text-text-dim">
            {included === null
              ? "selections this period"
              : `/ ${compact(included)} selections`}
          </span>
        </div>
        <span className="shrink-0 font-mono text-[11.5px] tracking-[0.1em] text-text-faint">
          {periodLabel(usage.periodStart, usage.periodEnd)}
        </span>
      </div>

      {included !== null && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-bg-panel">
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${Math.max(pct, used > 0 ? 2 : 0)}%` }}
          />
        </div>
      )}

      {footnote && (
        <p className="text-[13px] leading-[1.5] text-text-dim">{footnote}</p>
      )}
    </div>
  );
}
