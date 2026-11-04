"use client";

import { LoopRef, MetricRef } from "@qbrix/ui/next/entity";
import type { ListColumn } from "@qbrix/ui/next/list";
import { Menu } from "@qbrix/ui/next/menu";
import { StateDot } from "@qbrix/ui/next/state";
import { usePin } from "@/components/next/shell/pinned";
import { routes } from "@/config/routes";
import type { Metric, MetricLoop } from "@/lib/api/types";
import { metricLine } from "@/lib/metric/list";

function Subject({ metric }: { metric: Metric }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <MetricRef name={metric.name} className="n-body truncate font-medium" />
      <span className="n-body text-n-text-1">{metric.semantic}</span>
      <span className="n-meta text-n-text-3">{metricLine(metric)}</span>
    </div>
  );
}

function LoopState({ state }: { state: MetricLoop["state"] }) {
  if (state === "draft") return <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-n-line" />;
  return <StateDot state={state === "paused" ? "part" : "ok"} />;
}

function UsedBy({ metric }: { metric: Metric }) {
  if (metric.loops.length === 0) return <span className="n-meta text-n-text-3">no loop yet</span>;
  return (
    <ul className="flex flex-col gap-1">
      {metric.loops.map((loop) => (
        <li key={loop.id} className="n-body flex min-w-0 items-center gap-2">
          <LoopState state={loop.state} />
          <LoopRef name={loop.name} href={routes.next.loop(loop.key)} className="truncate" />
        </li>
      ))}
    </ul>
  );
}

function MetricMenu({ metric }: { metric: Metric }) {
  const pin = usePin({ kind: "metric", ref: metric.id, name: metric.name, key: metric.name, state: null });
  return <Menu items={[pin.menuItem]} label={`More actions for ${metric.name}`} />;
}

export const METRIC_COLUMNS: ListColumn<Metric>[] = [
  { key: "metric", label: "Metric", render: (metric) => <Subject metric={metric} /> },
  { key: "used", label: "Used by", width: "200px", render: (metric) => <UsedBy metric={metric} /> },
  { key: "menu", label: "", width: "28px", render: (metric) => <MetricMenu metric={metric} /> },
];
