import type { Metric } from "@/lib/api/types";
import { ago, windowLabel } from "../loop/fact";
import { metricTypeLabel } from "./new-metric";

/** "Conversion · 24 hours · version 1.0" */
export function metricLine(metric: Pick<Metric, "type" | "window_seconds" | "version">): string {
  return `${metricTypeLabel(metric.type)} · ${windowLabel(metric.window_seconds)} · version ${metric.version}`;
}

export function metricsCounters(metrics: Metric[], updatedAt: number, now: number): Record<string, string | undefined> {
  return {
    count: String(metrics.length),
    updated: updatedAt ? ago(new Date(updatedAt).toISOString(), now) : undefined,
  };
}
