"use client";

import { useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ColumnBar, DataRow, Cell } from "@qbrix/ui/components/data-table";
import type { Column } from "@qbrix/ui/components/data-table";
import { vizSeries, vizSeriesDim } from "@qbrix/ui/components/belief-viz";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { PageReveal, SkeletonTrack } from "@qbrix/ui/components/page-reveal";
import { cn } from "@qbrix/ui/lib/utils";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { insights as insightsApi } from "@/lib/api/insights";
import { policies as policiesApi } from "@/lib/api/policies";
import { useEntitlements } from "@/lib/entitlements";
import { routes } from "@/config/routes";
import { FeatureGate } from "@/lib/edition";
import { beliefDomain } from "@qbrix/ui/lib/observed-range";
import { leaderOf, runnerUpOf, selectionShares } from "./derive";
import { pct, num } from "./format";
import { AllocationRow } from "./allocation-row";
import type { Arm, ArmTimeseriesResponse } from "@/lib/api/types";

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;


// ── stat strip ──────────────────────────────────────────────────────────────

function Stat({
  label,
  value,
  delta,
  tone = "primary",
}: {
  label: string;
  value: string | null;
  delta?: { text: string; tone: "positive" | "danger" | "faint" } | null;
  tone?: "primary" | "accent";
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2">
      <span className="truncate text-[14px] text-text-dim">{label}</span>
      <span
        className={cn(
          "truncate font-mono text-[30px] tracking-[-1px]",
          tone === "accent" ? "text-accent" : "text-text-primary",
        )}
      >
        {value ?? "—"}
      </span>
      <span
        className={cn(
          "truncate text-[13px]",
          delta?.tone === "positive" && "text-positive",
          delta?.tone === "danger" && "text-danger",
          (!delta || delta.tone === "faint") && "text-text-faint",
        )}
      >
        {delta?.text ?? ""}
      </span>
    </div>
  );
}

// ── variants, without analytics ─────────────────────────────────────────────

// hoisted out of the page body so the loading state can draw the same bar —
// the column widths are half of what makes a skeleton line up with its content.
const ALLOCATION_COLUMNS: Column[] = [
  { label: "Variant" },
  { label: "Belief", width: 170 },
  { label: "Allocation", width: 240 },
  { label: "Share", width: 72, align: "right" },
  { label: "Reward", width: 78, align: "right" },
  { label: "Observed range", width: 96, align: "right" },
];

// board `APP · OSS · Experiment / Overview (EE disabled)`. every column of the
// allocation table is fed by the insight endpoints, so with no analytics store
// the left column renders nothing at all. these four fields are on the Arm rows
// Postgres already returns with the experiment — no extra request.
const VARIANT_COLUMNS: Column[] = [
  { label: "Variant" },
  { label: "Index", width: 96 },
  { label: "Arm ID", width: 260 },
  { label: "State", width: 110 },
];

function VariantsTable({
  arms,
  poolName,
}: {
  arms: Arm[];
  poolName: string | undefined;
}) {
  return (
    <>
      <div className="flex items-baseline justify-between gap-4 px-7 pb-3.5 pt-5">
        <h2 className="text-[17px] font-semibold tracking-[-0.3px] text-text-primary">
          Variants
        </h2>
        <span className="text-[13.5px] text-text-faint">
          from the pool · {arms.length} {arms.length === 1 ? "arm" : "arms"}
        </span>
      </div>

      <ColumnBar columns={VARIANT_COLUMNS} />

      {arms.length === 0 ? (
        <div className="px-7 py-12 text-[14px] text-text-dim">
          This pool has no variants.
        </div>
      ) : (
        arms.map((arm) => (
          <DataRow key={arm.id} height={72}>
            <Cell>
              <div className="flex items-center gap-[13px]">
                <span
                  className={cn(
                    "size-[9px] shrink-0 rounded-full",
                    vizSeries(arm.index),
                  )}
                />
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="truncate text-[15px] font-medium text-text-primary">
                    {arm.name}
                  </span>
                  <span className="truncate text-[13px] text-text-faint">
                    {poolName ?? "—"} · variant
                  </span>
                </div>
              </div>
            </Cell>
            <Cell width={96}>
              <span className="font-mono text-[12.5px] text-text-dim">
                {arm.index}
              </span>
            </Cell>
            <Cell width={260}>
              <span className="truncate font-mono text-[12.5px] text-text-dim">
                {arm.id}
              </span>
            </Cell>
            <Cell width={110}>
              <span
                className={cn(
                  "text-[13.5px]",
                  arm.is_active ? "text-text-secondary" : "text-text-faint",
                )}
              >
                {arm.is_active ? "Active" : "Inactive"}
              </span>
            </Cell>
          </DataRow>
        ))
      )}
    </>
  );
}

// ── right rail cards ────────────────────────────────────────────────────────

function KeyRow({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="shrink-0 text-[13.5px] text-text-dim">{k}</span>
      <span className="truncate text-[13.5px] text-text-secondary">{v}</span>
    </div>
  );
}

function RailCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 pb-5">
      <div className="flex items-center justify-between gap-4">
        <span className="text-[15px] font-medium text-text-primary">
          {title}
        </span>
        {action}
      </div>
      {children}
    </div>
  );
}

// ── loading ─────────────────────────────────────────────────────────────────

// the overview's own geometry: the stat strip, the allocation table and the
// right rail, at the heights they will occupy. the tab header above comes from
// the layout and is already on screen, so it is not redrawn here.
function OverviewSkeleton({ hasInsights }: { hasInsights: boolean }) {
  return (
    <div className="flex flex-1 flex-col">
      {hasInsights && (
        <div className="flex shrink-0 gap-6 border-b border-border-subtle px-7 py-[22px]">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex min-w-0 flex-1 flex-col gap-2">
              <Skeleton className="h-[14px] w-[96px]" />
              <Skeleton className="h-[38px] w-28" />
              <Skeleton className="h-[13px] w-[72px]" />
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-1 flex-col xl:flex-row">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-4 px-7 pb-3.5 pt-5">
            <Skeleton className="h-[17px] w-[142px]" />
            <Skeleton className="h-[13.5px] w-[96px]" />
          </div>

          <ColumnBar
            columns={hasInsights ? ALLOCATION_COLUMNS : VARIANT_COLUMNS}
          />

          {Array.from({ length: 3 }).map((_, i) => (
            <DataRow key={i} height={72}>
              <Cell>
                <div className="flex items-center gap-[13px]">
                  <Skeleton className="size-[9px] shrink-0 rounded-full" />
                  <div className="flex min-w-0 flex-col gap-1">
                    <Skeleton
                      className="h-[15px]"
                      style={{ width: 148 - i * 16 }}
                    />
                    <Skeleton className="h-[13px] w-[104px]" />
                  </div>
                </div>
              </Cell>
              {hasInsights ? (
                <>
                  <Cell width={170}>
                    <Skeleton className="h-[30px] w-full" />
                  </Cell>
                  <Cell width={240}>
                    <SkeletonTrack height={9} />
                  </Cell>
                  <Cell width={72} align="right">
                    <Skeleton className="ml-auto h-[15px] w-10" />
                  </Cell>
                  <Cell width={78} align="right">
                    <Skeleton className="ml-auto h-[15px] w-12" />
                  </Cell>
                  <Cell width={96} align="right">
                    <Skeleton className="ml-auto h-[15px] w-16" />
                  </Cell>
                </>
              ) : (
                <>
                  <Cell width={96}>
                    <Skeleton className="h-[12.5px] w-6" />
                  </Cell>
                  <Cell width={260}>
                    <Skeleton className="h-[12.5px] w-[200px]" />
                  </Cell>
                  <Cell width={110}>
                    <Skeleton className="h-[13.5px] w-14" />
                  </Cell>
                </>
              )}
            </DataRow>
          ))}
        </div>

        <div className="flex w-full shrink-0 flex-col gap-0 border-border-subtle px-[22px] py-5 xl:w-[344px] xl:border-l">
          {hasInsights && <Skeleton className="mb-6 h-[164px] rounded-[14px]" />}
          {Array.from({ length: 2 }).map((_, card) => (
            <div key={card} className="flex flex-col gap-3 pb-5">
              <Skeleton className="h-[15px] w-[104px]" />
              {Array.from({ length: 4 }).map((_, row) => (
                <div key={row} className="flex items-center justify-between gap-4">
                  <Skeleton className="h-[13.5px] w-[72px]" />
                  <Skeleton className="h-[13.5px] w-[88px]" />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── page ────────────────────────────────────────────────────────────────────

export default function ExperimentOverviewPage() {
  const params = useParams();
  const id = params.id as string;
  // both closed states show the variants table, but only one of them explains
  // itself with the note and only the other carries the upgrade card
  const { hasInsights, gate: entitlementGate } = useEntitlements();
  const insightGate = entitlementGate("insights");

  const experimentQuery = useQuery({
    queryKey: queryKeys.experiments.detail(id),
    queryFn: () => experimentsApi.get(id),
  });
  const experiment = experimentQuery.data;

  // the three windows are pinned once per mount. deriving them inline would
  // make a new query key on every render and refetch forever.
  const windows = useMemo(() => {
    const now = Date.now();
    return {
      day: { start_ms: now - DAY_MS },
      prevDay: { start_ms: now - 2 * DAY_MS, end_ms: now - DAY_MS },
    };
  }, []);

  // lifetime — shared with the layout's chip, one poll for both
  const lifetimeQuery = useQuery({
    queryKey: queryKeys.insights.experiment(id),
    queryFn: () => insightsApi.getStats(id),
    enabled: hasInsights,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
  const lifetime = lifetimeQuery.data;

  const todayQuery = useQuery({
    queryKey: queryKeys.insights.experiment(id, windows.day),
    queryFn: () => insightsApi.getStats(id, windows.day),
    enabled: hasInsights,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
  const today = todayQuery.data;

  // a closed window in the past — it barely moves, so it does not deserve the
  // hot interval
  const yesterdayQuery = useQuery({
    queryKey: queryKeys.insights.experiment(id, windows.prevDay),
    queryFn: () => insightsApi.getStats(id, windows.prevDay),
    enabled: hasInsights,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const yesterday = yesterdayQuery.data;

  const armsQuery = useQuery({
    queryKey: queryKeys.insights.arms(id),
    queryFn: () => insightsApi.getArmStats(id),
    enabled: hasInsights,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
  const { data: armAnalytics, dataUpdatedAt } = armsQuery;

  const policyQuery = useQuery({
    queryKey: ["policies"],
    queryFn: () => policiesApi.list(),
    staleTime: Infinity,
  });
  const policyList = policyQuery.data;

  // hoisted out of `ShareOverTime`. it owns a chart that renders nothing at all
  // until its data lands and then takes ~190px, so left in the child it was the
  // one thing on the page guaranteed to shift everything under it — after the
  // rest had already settled. its `Date.now()` also has to be pinned here or
  // the two components ask for two different windows.
  const shareParams = useMemo(() => {
    const now = Date.now();
    return {
      interval_ms: 6 * HOUR_MS,
      start_ms: now - 14 * DAY_MS,
      end_ms: now,
    };
  }, []);

  const shareQuery = useQuery({
    queryKey: queryKeys.insights.armSeries(id, shareParams),
    queryFn: () => insightsApi.getArmTimeseries(id, shareParams),
    enabled: hasInsights,
    refetchInterval: 60_000,
  });

  const arms = armAnalytics?.arms ?? [];
  const leader = leaderOf(arms);
  const runnerUp = runnerUpOf(arms);
  const shares = selectionShares(arms);
  const domain = beliefDomain(
    arms.map((a) => ({ mean: a.avg_reward, count: a.feedback_count ?? 0 })),
  );

  const gate = experiment?.feature_gate ?? null;
  const policy = policyList?.policies.find((p) => p.name === experiment?.policy);

  // ── stat derivations ──
  const selections24h = today?.total_selections ?? null;
  const prev24h = yesterday?.total_selections ?? null;
  const selectionsDelta =
    selections24h !== null && prev24h !== null && prev24h > 0
      ? (selections24h - prev24h) / prev24h
      : null;

  const rewardRate = lifetime?.avg_reward ?? null;
  const rewardDelta =
    today?.avg_reward != null && yesterday?.avg_reward != null
      ? today.avg_reward - yesterday.avg_reward
      : null;

  const feedbackRate =
    lifetime && lifetime.total_selections > 0
      ? lifetime.total_feedback / lifetime.total_selections
      : null;

  const gateServed =
    lifetime && lifetime.total_selections > 0
      ? lifetime.default_selections / lifetime.total_selections
      : null;

  // ── verdict ──
  const lift =
    leader?.avg_reward != null &&
    runnerUp?.avg_reward != null &&
    runnerUp.avg_reward > 0
      ? (leader.avg_reward - runnerUp.avg_reward) / runnerUp.avg_reward
      : null;

  const updatedAgo = dataUpdatedAt
    ? Math.max(0, Math.round((Date.now() - dataUpdatedAt) / 1000))
    : null;

  // six requests fanned across a stat strip, a table, a chart and two rail
  // cards — every one of which used to appear on its own clock. `experiment`
  // and `policyList` are in it even without insights, because the rail's Policy
  // and Feature gate cards are drawn from them on every deployment.
  const ready = usePageReady([
    experimentQuery,
    policyQuery,
    lifetimeQuery,
    todayQuery,
    yesterdayQuery,
    armsQuery,
    shareQuery,
  ]);

  return (
    <PageReveal
      ready={ready}
      className="flex flex-1 flex-col"
      skeleton={<OverviewSkeleton hasInsights={hasInsights} />}
    >
      {hasInsights ? (
        <div className="flex shrink-0 gap-6 border-b border-border-subtle px-7 py-[22px]">
          <Stat
            label="Selections · 24h"
            value={selections24h !== null ? num(selections24h) : null}
            delta={
              selectionsDelta !== null
                ? {
                    text: `${selectionsDelta >= 0 ? "+" : ""}${(selectionsDelta * 100).toFixed(1)}%`,
                    tone: selectionsDelta >= 0 ? "positive" : "danger",
                  }
                : null
            }
          />
          <Stat
            label="Reward rate"
            tone="accent"
            value={rewardRate !== null ? pct(rewardRate, 2) : null}
            delta={
              rewardDelta !== null
                ? {
                    text: `${rewardDelta >= 0 ? "+" : ""}${(rewardDelta * 100).toFixed(2)} pts`,
                    tone: rewardDelta >= 0 ? "positive" : "danger",
                  }
                : null
            }
          />
          <Stat
            label="Feedback rate"
            value={feedbackRate !== null ? pct(feedbackRate) : null}
            delta={{ text: "of selections", tone: "faint" }}
          />
          <Stat
            label="Unique contexts"
            value={
              lifetime?.unique_contexts != null
                ? num(lifetime.unique_contexts)
                : null
            }
            // the board says "last 14 days"; this is the lifetime figure, and a
            // fourth windowed request for one sublabel is not worth the poll
            delta={{ text: "all time", tone: "faint" }}
          />
          <Stat
            label="Gate-served"
            value={gateServed !== null ? pct(gateServed) : null}
            delta={{ text: "default arm", tone: "faint" }}
          />
        </div>
      ) : null}

      <div className="flex flex-1 flex-col xl:flex-row">
        <div className="flex min-w-0 flex-1 flex-col">
          {hasInsights ? (
            <>
              <div className="flex items-center justify-between gap-4 px-7 pb-3.5 pt-5">
                <h2 className="text-[17px] font-semibold tracking-[-0.3px] text-text-primary">
                  Traffic allocation
                </h2>
                {updatedAgo !== null && (
                  <span className="text-[13.5px] text-text-faint">
                    updated {updatedAgo === 0 ? "just now" : `${updatedAgo}s ago`}
                  </span>
                )}
              </div>

              <ColumnBar columns={ALLOCATION_COLUMNS} />

              {arms.length === 0 ? (
                <div className="px-7 py-12 text-[14px] text-text-dim">
                  No selections recorded yet.
                </div>
              ) : (
                arms.map((arm) => (
                  <AllocationRow
                    key={arm.arm_index}
                    arm={arm}
                    share={shares.get(arm.arm_index) ?? 0}
                    isLeader={leader?.arm_index === arm.arm_index}
                    domain={domain}
                  />
                ))
              )}

              <p className="px-7 py-4 text-[12.5px] leading-[1.5] text-text-faint">
                Observed range and belief shapes are derived from selection and
                feedback counts — not the learner&apos;s posterior.
              </p>

              <ShareOverTime data={shareQuery.data} />
            </>
          ) : (
            <>
              <VariantsTable
                arms={experiment?.pool?.arms ?? []}
                poolName={experiment?.pool?.name}
              />

              {/* absent only. this explains an OSS *deployment*; a locked tenant's
                  answer is their plan tier, and the card below already says so. */}
              {insightGate === "absent" && (
                <p className="px-7 py-4 text-[12.5px] leading-[1.5] text-text-faint">
                  Selection counts, reward rates and allocation come from the
                  analytics store, which the enterprise trace service writes.
                  Without it this table shows only what Postgres holds: the
                  pool&apos;s arms.
                </p>
              )}

              {/* null when absent — the board draws no OSS upgrade prompt because
                  there is nothing to upgrade to */}
              <FeatureGate surface="experiment.overview" />
            </>
          )}
        </div>

        <div className="flex w-full shrink-0 flex-col gap-0 border-border-subtle px-[22px] py-5 xl:w-[344px] xl:border-l">
          {hasInsights && leader && (
            <div className="mb-6 flex flex-col gap-[13px] rounded-[14px] bg-accent/[0.06] p-[18px]">
              <div className="flex items-center gap-2.5">
                <span className="size-2 rounded-full bg-accent" />
                <span className="text-[15px] font-medium text-text-primary">
                  {leader.arm_name} is ahead
                </span>
              </div>
              <p className="text-[13.5px] leading-[1.5] text-text-secondary">
                {lift !== null && runnerUp
                  ? `${lift >= 0 ? "+" : ""}${(lift * 100).toFixed(0)}% reward rate vs next best · ${runnerUp.arm_name}, from ${num(leader.feedback_count ?? 0)} feedback events.`
                  : `Leading on ${num(leader.feedback_count ?? 0)} feedback events. No second arm has feedback yet.`}
              </p>
              <Link
                href={routes.experimentGate(id)}
                className="flex h-[38px] items-center justify-center rounded-[19px] bg-accent text-[14px] font-semibold text-bg transition-colors hover:bg-accent/90"
              >
                Commit via feature gate
              </Link>
            </div>
          )}

          <RailCard
            title="Policy"
            action={
              <Link
                href={routes.experimentPolicy(id)}
                className="text-[13.5px] text-text-dim transition-colors hover:text-text-primary"
              >
                Edit
              </Link>
            }
          >
            <KeyRow k="Algorithm" v={experiment?.policy ?? "—"} />
            <KeyRow k="Category" v={policy?.category ?? "—"} />
            {Object.entries(experiment?.policy_params ?? {}).map(([k, v]) => (
              <KeyRow key={k} k={k} v={String(v)} />
            ))}
          </RailCard>

          <RailCard
            title="Feature gate"
            action={
              <Link
                href={routes.experimentGate(id)}
                className="text-[13.5px] text-text-dim transition-colors hover:text-text-primary"
              >
                Edit
              </Link>
            }
          >
            <KeyRow
              k="Status"
              v={
                <span className={gate?.enabled ? "text-positive" : undefined}>
                  {gate ? (gate.enabled ? "Enabled" : "Disabled") : "Not configured"}
                </span>
              }
            />
            <KeyRow
              k="Rollout"
              v={gate ? `${gate.rollout_percentage}%` : "—"}
            />
            <KeyRow
              k="Targeting"
              v={
                gate && gate.rules.length > 0
                  ? gate.rules
                      .map((r) => `${r.key} ${r.operator} ${String(r.value)}`)
                      .join(", ")
                  : "None"
              }
            />
            <KeyRow k="Default arm" v={gate?.default_arm_name ?? "—"} />
          </RailCard>
        </div>
      </div>
    </PageReveal>
  );
}

// board `APP · Experiment / Overview` / Conv. one column per bucket, each arm's
// segment sized by its share *of that bucket* — so the column always fills and
// the shape reads as reallocation over time rather than as traffic volume.
function ShareOverTime({ data }: { data: ArmTimeseriesResponse | undefined }) {
  const buckets = data?.data ?? [];
  if (buckets.length === 0) return null;

  const first = buckets[0];
  const last = buckets[buckets.length - 1];
  const shareIn = (b: (typeof buckets)[number], index: number) => {
    const total = b.arms.reduce((s, a) => s + a.selections, 0);
    if (total === 0) return 0;
    return (b.arms.find((a) => a.arm_index === index)?.selections ?? 0) / total;
  };

  // headline the arm that ends on top — the one the policy converged toward
  const top = [...last.arms].sort((a, b) => b.selections - a.selections)[0];
  const from = top ? shareIn(first, top.arm_index) : null;
  const to = top ? shareIn(last, top.arm_index) : null;

  return (
    <div className="flex flex-col gap-3 px-7 pb-[22px] pt-5">
      <div className="flex items-center justify-between gap-4">
        <span className="text-[15px] font-medium text-text-primary">
          Share over time
        </span>
        {from !== null && to !== null && (
          <span className="text-[13px] text-text-faint">
            {top.arm_name}: {pct(from)} → {pct(to)} over 14 days
          </span>
        )}
      </div>
      <div className="flex h-[92px] items-end gap-px">
        {buckets.map((b) => (
          <div
            key={b.timestamp_ms}
            className="flex h-full min-w-0 flex-1 flex-col justify-end"
          >
            {[...b.arms]
              .sort((a, z) => a.arm_index - z.arm_index)
              .map((a) => {
                const s = shareIn(b, a.arm_index);
                if (s <= 0) return null;
                return (
                  <div
                    key={a.arm_index}
                    className="flex flex-col"
                    style={{ height: `${s * 100}%` }}
                  >
                    <span
                      className={cn("h-[1.5px] shrink-0", vizSeries(a.arm_index))}
                    />
                    <span
                      className={cn("min-h-0 flex-1", vizSeriesDim(a.arm_index))}
                    />
                  </div>
                );
              })}
          </div>
        ))}
      </div>
    </div>
  );
}
