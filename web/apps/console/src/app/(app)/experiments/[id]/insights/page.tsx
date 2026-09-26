"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { insights as insightsApi } from "@/lib/api/insights";
import { useEntitlements, useFeatureRoute } from "@/lib/entitlements";
import { FeatureGate } from "@/lib/edition";
import { num, pct } from "../format";
import { useHeaderTool } from "../header-actions";
import {
  BucketControl,
  RangeControl,
  defaultInterval,
  rangeParams,
} from "./range";
import type { RangePreset } from "./range";
import {
  BarSeries,
  ChartEmpty,
  ChartPanel,
  Legend,
  RankedBars,
  StackedColumns,
} from "./charts";
import type { StackPoint } from "./charts";
import { byArmIndex, cumulativeTotal, liftVsControl } from "./derive";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes } from "@/config/routes";

// board `APP · Experiment / Insights`. KPI strip on a hairline, then a 2×2 grid
// of chart panels. panels are correct here — a chart is a panel, a list is not
// (the surface rule).
//
// three board elements are not built, because nothing can fill them:
//   · the "fixed 25/25/25/25" counterfactual on Cumulative reward — it needs
//     per-arm reward over time, and /timeseries/rewards blends all arms into
//     one average. filed as a backend gap; the panel ships one series.
//   · "Selections by segment" — ClickHouse holds context_metadata as an opaque
//     JSON blob and no endpoint groups on it. Reward rate over time takes the
//     slot, which is real and was otherwise unused.
//   · "Time to leader — first stable leader" — a convergence claim with no
//     record behind it. Selections takes the KPI slot.
// and "Export CSV" is omitted: no endpoint.

// the label follows the *range*, not the bucket size: 14d/6h buckets are
// sub-day, but "18:00" repeated across two weeks says nothing about which day.
function bucketLabel(ms: number, preset: RangePreset): string {
  const d = new Date(ms);
  return preset === "24h"
    ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

function Kpi({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub: string;
  accent?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2">
      <span className="text-[14px] text-text-dim">{label}</span>
      <span
        className={
          accent
            ? "text-[29px] tracking-[-1px] text-accent"
            : "text-[29px] tracking-[-1px] text-text-primary"
        }
      >
        {value}
      </span>
      <span className="text-[13px] text-text-faint">{sub}</span>
    </div>
  );
}

export default function ExperimentInsightsPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <GuardedRoute
      surface="experiment.insights"
      backHref={routes.experimentOverview(id)}
      overviewHref={routes.experimentOverview(id)}
    >
      <ExperimentInsightsPageContent />
    </GuardedRoute>
  );
}

function ExperimentInsightsPageContent() {
  const params = useParams();
  const experimentId = params.id as string;
  const { hasInsights } = useEntitlements();
  useFeatureRoute("insights");

  // preset and bucket move together: each range offers its own bucket set, so
  // changing the range resets the bucket to that range's default rather than
  // carrying over one the new range does not offer
  const [sel, setSel] = useState<{ preset: RangePreset; intervalMs: number }>(
    () => ({ preset: "14d", intervalMs: defaultInterval("14d") }),
  );
  const { preset, intervalMs } = sel;

  // pinned: `Date.now()` inline would mint a new query key every render
  const [now] = useState(() => Date.now());
  const range = useMemo(
    () => rangeParams(preset, now, intervalMs),
    [preset, now, intervalMs],
  );
  const window = useMemo(
    () => ({ start_ms: range.start_ms, end_ms: range.end_ms }),
    [range],
  );

  // only the range goes in the head — the bucket sits over the chart grid, see
  // the note in range.tsx
  useHeaderTool(
    useMemo(
      () =>
        hasInsights ? (
          <RangeControl
            preset={preset}
            onChange={(p) =>
              setSel({ preset: p, intervalMs: defaultInterval(p) })
            }
          />
        ) : null,
      [preset, hasInsights],
    ),
  );

  const enabled = hasInsights;

  const experimentQuery = useQuery({
    queryKey: queryKeys.experiments.detail(experimentId),
    queryFn: () => experimentsApi.get(experimentId),
  });
  const experiment = experimentQuery.data;

  const statsQuery = useQuery({
    queryKey: queryKeys.insights.experiment(experimentId, window),
    queryFn: () => insightsApi.getStats(experimentId, window),
    enabled,
  });

  const funnelQuery = useQuery({
    queryKey: queryKeys.insights.funnel(experimentId, window),
    queryFn: () => insightsApi.getFeedbackFunnel(experimentId, window),
    enabled,
  });

  const armsQuery = useQuery({
    queryKey: queryKeys.insights.arms(experimentId, window),
    queryFn: () => insightsApi.getArmStats(experimentId, window),
    enabled,
  });

  const cumulativeQuery = useQuery({
    queryKey: queryKeys.insights.cumulative(experimentId, range),
    queryFn: () => insightsApi.getCumulativeReward(experimentId, range),
    enabled,
  });

  const armSeriesQuery = useQuery({
    queryKey: queryKeys.insights.armSeries(experimentId, range),
    queryFn: () => insightsApi.getArmTimeseries(experimentId, range),
    enabled,
  });

  const rewardSeriesQuery = useQuery({
    queryKey: queryKeys.insights.rewards(experimentId, range),
    queryFn: () => insightsApi.getRewardTimeseries(experimentId, range),
    enabled,
  });

  const arms = useMemo(
    () => byArmIndex(armsQuery.data?.arms ?? []),
    [armsQuery.data],
  );

  const lift = useMemo(
    () => liftVsControl(arms, experiment),
    [arms, experiment],
  );

  const cumulativePoints = useMemo(
    () =>
      (cumulativeQuery.data?.data ?? []).map((p) => ({
        key: String(p.timestamp_ms),
        value: p.cumulative_reward,
        label: bucketLabel(p.timestamp_ms, preset),
      })),
    [cumulativeQuery.data, preset],
  );

  const stackPoints: StackPoint[] = useMemo(
    () =>
      (armSeriesQuery.data?.data ?? []).map((p) => ({
        key: String(p.timestamp_ms),
        label: bucketLabel(p.timestamp_ms, preset),
        segments: byArmIndex(p.arms).map((a) => ({
          index: a.arm_index,
          name: a.arm_name,
          value: a.selections,
        })),
      })),
    [armSeriesQuery.data, preset],
  );

  const rewardPoints = useMemo(
    () =>
      (rewardSeriesQuery.data?.data ?? []).map((p) => ({
        key: String(p.timestamp_ms),
        value: p.avg_reward,
        label: bucketLabel(p.timestamp_ms, preset),
      })),
    [rewardSeriesQuery.data, preset],
  );

  // six requests behind five KPIs and four charts. the panel titles, the
  // legends' frame and the bucket control are chrome and are already drawn —
  // what waits is every value and every plot, and they now wait as one thing
  // rather than appearing over four separate frames.
  const ready = usePageReady([
    experimentQuery,
    statsQuery,
    funnelQuery,
    armsQuery,
    cumulativeQuery,
    armSeriesQuery,
    rewardSeriesQuery,
  ]);

  // every query below would 403 without the entitlement
  if (!hasInsights) return <FeatureGate surface="experiment.insights" />;

  const stats = statsQuery.data;

  return (
    <div className="flex flex-col">
      <div className="flex gap-8 border-b border-border-subtle px-7 py-[22px]">
        {!ready || !stats ? (
          [0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-[18px] w-28" />
              <Skeleton className="h-[38px] w-24" />
              <Skeleton className="h-[17px] w-32" />
            </div>
          ))
        ) : (
          <>
            <Kpi
              label="Cumulative reward"
              value={num(cumulativeTotal(cumulativeQuery.data?.data ?? []))}
              sub="reward attributed"
            />
            <Kpi
              label="Lift vs control"
              value={lift === null ? "—" : `${lift > 0 ? "+" : ""}${pct(lift)}`}
              sub="leader over control"
              accent={lift !== null && lift > 0}
            />
            <Kpi
              label="Feedback rate"
              value={
                funnelQuery.data ? pct(funnelQuery.data.feedback_rate) : "—"
              }
              sub="of selections with feedback"
            />
            <Kpi
              label="Unique contexts"
              value={num(stats.unique_contexts)}
              sub="distinct context ids"
            />
            <Kpi
              label="Selections"
              value={num(stats.total_selections)}
              sub="in this range"
            />
          </>
        )}
      </div>

      <div className="flex flex-col gap-[18px] px-7 pb-6 pt-4">
        <div className="flex justify-end">
          <BucketControl
            preset={preset}
            intervalMs={intervalMs}
            onChange={(ms) => setSel((s) => ({ ...s, intervalMs: ms }))}
          />
        </div>

        <div className="flex gap-[18px]">
          <div className="min-w-0 flex-1">
            <ChartPanel
              title="Cumulative reward"
              note="running total of attributed reward"
              legend={<Legend items={[{ label: "qbrix adaptive", index: 0 }]} />}
            >
              {!ready ? (
                <Skeleton className="h-[126px] w-full" />
              ) : (
                <BarSeries points={cumulativePoints} />
              )}
            </ChartPanel>
          </div>
          <div className="w-[430px] shrink-0">
            <ChartPanel title="Reward rate per variant">
              {!ready ? (
                <Skeleton className="h-[159px] w-full" />
              ) : (
                <RankedBars
                  rows={arms.map((a) => ({
                    index: a.arm_index,
                    name: a.arm_name,
                    value: a.avg_reward ?? 0,
                    display: a.avg_reward === null ? "—" : pct(a.avg_reward, 2),
                  }))}
                />
              )}
            </ChartPanel>
          </div>
        </div>

        <div className="flex gap-[18px]">
          <div className="min-w-0 flex-1">
            <ChartPanel
              title="Traffic share over time"
              legend={
                <Legend
                  items={arms.map((a) => ({
                    label: a.arm_name,
                    index: a.arm_index,
                  }))}
                />
              }
            >
              {!ready ? (
                <Skeleton className="h-[180px] w-full" />
              ) : (
                <StackedColumns points={stackPoints} />
              )}
            </ChartPanel>
          </div>
          <div className="w-[430px] shrink-0">
            <ChartPanel
              title="Reward rate over time"
              note="all variants"
            >
              {!ready ? (
                <Skeleton className="h-[159px] w-full" />
              ) : rewardPoints.length === 0 ? (
                <ChartEmpty height={159} />
              ) : (
                <BarSeries points={rewardPoints} height={138} />
              )}
            </ChartPanel>
          </div>
        </div>
      </div>
    </div>
  );
}
