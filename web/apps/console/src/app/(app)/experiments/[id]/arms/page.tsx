"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { ColumnBar, DataRow, Cell } from "@qbrix/ui/components/data-table";
import type { Column } from "@qbrix/ui/components/data-table";
import { BeliefViz, vizSeries } from "@qbrix/ui/components/belief-viz";
import { BeliefAxis } from "@qbrix/ui/components/belief-axis";
import {
  observedRange,
  beliefDomain,
  snapDomain,
} from "@qbrix/ui/lib/observed-range";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { cn } from "@qbrix/ui/lib/utils";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { insights as insightsApi } from "@/lib/api/insights";
import { useEntitlements } from "@/lib/entitlements";
import { routes } from "@/config/routes";
import { FeatureGate } from "@/lib/edition";
import type { ArmStats } from "@/lib/api/types";
import { leaderOf, selectionShares } from "../derive";
import { pct, num } from "../format";
import { useResetExperiment } from "../use-reset-experiment";
import { GuardedRoute } from "@/components/shell/mobile-guard";

// board `APP · Experiment / Arms`
const BELIEF_W = 320;
const BELIEF_H = 56;
const BUCKETS = 52;

const COLUMNS: Column[] = [
  { label: "Variant" },
  { label: "Belief · P(reward)", width: BELIEF_W },
  { label: "Mean", width: 78, align: "right" },
  { label: "Observed range", width: 110, align: "right" },
  { label: "α / β", width: 118, align: "right", preserveCase: true },
  { label: "Selections", width: 104, align: "right" },
  { label: "Share", width: 78, align: "right" },
];

// the same fit the curve is drawn from — α = mean·n + 1, β = (1−mean)·n + 1.
// exposed as a column because the board asks for it, and it is the honest way
// to show how much evidence is behind a shape: a wide curve and a small α+β
// are the same fact stated twice.
function betaParams(mean: number | null, count: number) {
  if (mean === null || count <= 0) return null;
  const p = Math.min(1, Math.max(0, mean));
  return { alpha: p * count + 1, beta: (1 - p) * count + 1 };
}

function FooterCard({
  title,
  body,
  onClick,
  href,
}: {
  title: string;
  body: string;
  onClick?: () => void;
  href?: string;
}) {
  const inner = (
    <>
      <span className="text-[15px] font-medium text-text-primary">{title}</span>
      <span className="text-[13px] leading-[1.5] text-text-dim">{body}</span>
    </>
  );

  const base =
    "flex min-w-0 flex-1 flex-col gap-2 rounded-[12px] border border-border-subtle bg-bg-raised p-[18px] text-left transition-colors hover:bg-bg-hover";

  if (href) {
    return (
      <Link href={href} className={base}>
        {inner}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} className={base}>
      {inner}
    </button>
  );
}

export default function ArmsTabPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <GuardedRoute
      surface="experiment.arms"
      backHref={routes.experimentOverview(id)}
      overviewHref={routes.experimentOverview(id)}
    >
      <ArmsTabContent />
    </GuardedRoute>
  );
}

function ArmsTabContent() {
  const params = useParams();
  const experimentId = params.id as string;
  const { hasInsights } = useEntitlements();
  const reset = useResetExperiment(experimentId);

  const experimentQuery = useQuery({
    queryKey: queryKeys.experiments.detail(experimentId),
    queryFn: () => experimentsApi.get(experimentId),
  });
  const experiment = experimentQuery.data;

  // same key as the layout and Overview — one poll serves all three
  const armsQuery = useQuery({
    queryKey: queryKeys.insights.arms(experimentId),
    queryFn: () => insightsApi.getArmStats(experimentId),
    enabled: hasInsights,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
  const armAnalytics = armsQuery.data;

  // the belief axis is scaled from the arm stats, so revealing on `experiment`
  // alone drew the table and then re-scaled every rail under it.
  const ready = usePageReady([experimentQuery, armsQuery]);

  const arms = experiment?.pool?.arms ?? [];
  const stats = armAnalytics?.arms ?? [];
  const leader = leaderOf(stats);
  const shares = selectionShares(stats);

  // Arms draws an axis, so the domain snaps to round ticks. Overview has no
  // axis and keeps the tight fit — see `snapDomain`.
  const { domain, ticks } = snapDomain(
    beliefDomain(
      stats.map((s) => ({ mean: s.avg_reward, count: s.feedback_count ?? 0 })),
    ),
  );

  // decimals come from the tick *step*, not the value — deciding per value gives
  // "0.0%" next to "20%" on the same rail
  const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
  const tickDecimals = step >= 0.01 ? 0 : step >= 0.001 ? 1 : 2;

  if (!ready) {
    return (
      <div className="flex flex-col gap-3 px-7 py-6">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!hasInsights) return <FeatureGate surface="experiment.arms" />;

  const rows = arms.map((arm) => ({
    arm,
    stat: stats.find((s) => s.arm_index === arm.index),
  }));

  return (
    <div className="flex flex-col">
      <div className="mx-7 mt-5 flex items-start gap-2.5 rounded-[10px] bg-viz-2-soft px-3.5 py-3">
        <Info size={15} className="mt-[1px] shrink-0 text-viz-2" />
        <p className="text-[13px] leading-[1.5] text-text-secondary">
          The curve is an estimate of each variant&apos;s reward, shaped from its
          observed count and spread — not the learner&apos;s posterior, which the
          API does not expose.
        </p>
      </div>

      <ColumnBar columns={COLUMNS} className="mt-5" />

      {rows.length === 0 ? (
        <div className="px-7 py-12 text-[14px] text-text-dim">
          This pool has no variants.
        </div>
      ) : (
        rows.map(({ arm, stat }) => (
          <ArmRow
            key={arm.id}
            name={arm.name}
            index={arm.index}
            stat={stat}
            share={shares.get(arm.index) ?? 0}
            isLeader={leader?.arm_index === arm.index}
            domain={domain}
          />
        ))
      )}

      {/* the axis only means anything sitting exactly under the curves, so the
          rail mirrors the whole column grid rather than using one flex spacer —
          a single spacer absorbs all the slack and lands the axis at the far
          right, which is what it did on the first pass. */}
      {rows.length > 0 && (
        <div className="flex px-7 pt-2.5" style={{ gap: 18 }}>
          {COLUMNS.map((col, i) => (
            <div
              key={col.label}
              className={cn("shrink-0", col.width === undefined && "min-w-0 flex-1")}
              style={col.width !== undefined ? { width: col.width } : undefined}
            >
              {i === 1 && (
                <BeliefAxis
                  ticks={ticks}
                  domain={domain}
                  width={BELIEF_W}
                  format={(v) => pct(v, tickDecimals)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* the board draws a third card here, "Add a variant". a pool's arms are
          immutable *by design* — they are fixed at creation and will never be
          editable, so this is not an endpoint waiting to be written. the card
          is omitted rather than shown inert: a dead affordance advertises a
          feature that is deliberately absent. the board should lose it too. */}
      <div className="flex flex-col gap-3 px-7 pb-7 pt-8 sm:flex-row">
        <FooterCard
          title="Pin a variant"
          body="Force all eligible traffic to one variant without ending the experiment."
          href={routes.experimentGate(experimentId)}
        />
        <FooterCard
          title="Reset beliefs"
          body="Clear accumulated evidence and start learning from scratch."
          onClick={reset.open}
        />
      </div>

      {reset.dialog}
    </div>
  );
}

function ArmRow({
  name,
  index,
  stat,
  share,
  isLeader,
  domain,
}: {
  name: string;
  index: number;
  stat: ArmStats | undefined;
  share: number;
  isLeader: boolean;
  domain: [number, number];
}) {
  const mean = stat?.avg_reward ?? null;
  const feedback = stat?.feedback_count ?? 0;
  const range = mean !== null ? observedRange(mean, feedback) : null;
  const beta = betaParams(mean, feedback);

  return (
    <DataRow height={92} className={isLeader ? "bg-accent/[0.03]" : undefined}>
      <Cell>
        <div className="flex items-center gap-[13px]">
          <span className={cn("size-[9px] shrink-0 rounded-full", vizSeries(index))} />
          <div className="flex min-w-0 flex-col gap-1">
            <span className="truncate text-[15px] font-medium text-text-primary">
              {name}
            </span>
            {/* the board reads "leader · narrow posterior" here, which
                contradicts the note above the table. observed vocabulary only. */}
            <span className="truncate text-[13px] text-text-faint">
              {isLeader ? "leading · " : ""}n={num(feedback)}
            </span>
          </div>
        </div>
      </Cell>

      <Cell width={BELIEF_W}>
        <BeliefViz
          mean={mean}
          count={feedback}
          series={index}
          domain={domain}
          buckets={BUCKETS}
          width={BELIEF_W}
          height={BELIEF_H}
        />
      </Cell>

      <Cell width={78} align="right">
        <span
          className={cn(
            "font-mono text-[15px] tracking-[0.3px]",
            isLeader ? "text-accent" : "text-text-primary",
          )}
        >
          {mean !== null ? pct(mean, 2) : "—"}
        </span>
      </Cell>

      <Cell width={110} align="right">
        <span className="font-mono text-[13px] tracking-[0.3px] text-text-dim">
          {range ? `${(range.lo * 100).toFixed(2)} – ${pct(range.hi, 2)}` : "—"}
        </span>
      </Cell>

      <Cell width={118} align="right">
        <span className="font-mono text-[13px] tracking-[0.3px] text-text-dim">
          {beta
            ? `${Math.round(beta.alpha).toLocaleString()} / ${Math.round(beta.beta).toLocaleString()}`
            : "—"}
        </span>
      </Cell>

      <Cell width={104} align="right">
        <span className="font-mono text-[13px] tracking-[0.3px] text-text-dim">
          {num(stat?.selections ?? 0)}
        </span>
      </Cell>

      <Cell width={78} align="right">
        <span className="font-mono text-[15px] tracking-[0.3px] text-text-primary">
          {pct(share)}
        </span>
      </Cell>
    </DataRow>
  );
}
