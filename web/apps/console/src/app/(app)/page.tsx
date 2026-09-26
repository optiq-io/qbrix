"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { buttonClass } from "@qbrix/ui/components/button";
import { PageHead, SectionHead } from "@qbrix/ui/components/page-head";
import { ColumnBar, DataRow, Cell } from "@qbrix/ui/components/data-table";
import type { Column } from "@qbrix/ui/components/data-table";
import { AccentDot } from "@qbrix/ui/components/accent-dot";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import {
  PageReveal,
  SkeletonTrack,
  EmptyTrack,
} from "@qbrix/ui/components/page-reveal";
import { EmptyState } from "@qbrix/ui/components/empty-state";
import { ExperimentsEmptyIcon } from "@qbrix/ui/components/empty-icons";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { pools as poolsApi } from "@/lib/api/pools";
import { runtime } from "@/lib/api/runtime";
import { insights as insightsApi } from "@/lib/api/insights";
import { events as eventsApi } from "@/lib/api/events";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { useEntitlements } from "@/lib/entitlements";
import { useAuth } from "@/lib/auth/context";
import { routes } from "@/config/routes";
import { colorForArmIndex } from "@/components/insights/arm-colors";
import { FirstRunHome } from "@/components/first-run/first-run-home";
import { useServiceHealth } from "@/components/shell/service-health";
import type { ArmStats, Experiment, Pool, UnifiedEvent } from "@/lib/api/types";
import { ErrorState } from "@qbrix/ui/components/error-state";
import { apiErrorCode } from "@/lib/api/handle-error";

type FilterTab = "all" | "active" | "paused";

// board `APP · Home` — EXPERIMENT fills, the rest are fixed
const COLUMNS: Column[] = [
  { label: "Experiment" },
  { label: "Leader", width: 150 },
  { label: "Reward", width: 84, align: "right" },
  { label: "Feedback", width: 108, align: "right" },
  { label: "Allocation", width: 230 },
];

// board `APP · OSS · Home (EE disabled)`. every column above except the first
// is fed by insightsApi, so without it they render "—" five rows deep over an
// empty allocation rail — four columns measuring nothing. these four need no
// analytics at all.
const CORE_COLUMNS: Column[] = [
  { label: "Experiment" },
  { label: "Policy", width: 190 },
  { label: "Gate", width: 120 },
  { label: "State", width: 110 },
];

const SERVICE_COUNT = 3;
const RAIL_POOL_LIMIT = 6;

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

function compact(n: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(n);
}

function relativeTime(ms: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

// the board's first row reads "100% · committed". `committed` is illustrative —
// it occurs once in the whole design and no field on GateConfigResponse carries
// it. the rules count is real and fills the same second segment.
function gateSummary(exp: Experiment): string {
  const gate = exp.feature_gate;
  if (!gate) return "—";
  if (!gate.enabled) return "off";
  const rules = gate.rules?.length ?? 0;
  const pct = `${gate.rollout_percentage}%`;
  return rules > 0 ? `${pct} · ${rules} ${rules === 1 ? "rule" : "rules"}` : pct;
}

// the allocation bar animates when allocation actually moves, and never on
// arrival. if every bar slid in on page load the motion would stop
// meaning "the learner shifted weight" and become decoration.
//
// mounting is the wrong gate for that, and was the bug: the row mounts on the
// experiment list and its arm stats land a round trip later, by which point
// "after mount" is long true — so every load animated every bar out of the
// equal-split fallback, staging a reallocation that never happened. the gate is
// having drawn real allocation *before*, which is only ever true on a change.
function useAfterFirstData(hasData: boolean): boolean {
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    if (!hasData || drawn) return;
    const id = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(id);
  }, [hasData, drawn]);
  return drawn;
}

type Derived = {
  leader: string | null;
  reward: number | null;
  feedback: number;
  segments: { index: number; fraction: number }[] | null;
};

function derive(exp: Experiment, armStats: ArmStats[] | undefined): Derived {
  if (!armStats || armStats.length === 0) {
    return { leader: null, reward: null, feedback: 0, segments: null };
  }
  const selections = armStats.reduce((s, a) => s + (a.selections ?? 0), 0);
  const feedback = armStats.reduce((s, a) => s + (a.feedback_count ?? 0), 0);

  // avg_reward is a per-arm mean over that arm's feedback, so the experiment
  // mean has to be weighted by feedback count — not a mean of means.
  const rewarded = armStats.filter(
    (a) => a.avg_reward !== null && (a.feedback_count ?? 0) > 0,
  );
  const weighted = rewarded.reduce(
    (s, a) => s + (a.avg_reward as number) * (a.feedback_count ?? 0),
    0,
  );
  const reward = feedback > 0 && rewarded.length > 0 ? weighted / feedback : null;

  const top = [...armStats].sort(
    (a, b) => (b.selections ?? 0) - (a.selections ?? 0),
  )[0];
  const leader =
    top && selections > 0
      ? (exp.pool?.arms.find((a) => a.index === top.arm_index)?.name ??
        top.arm_name ??
        `arm ${top.arm_index}`)
      : null;

  const segments =
    selections > 0
      ? armStats
          .map((a) => ({
            index: a.arm_index,
            fraction: (a.selections ?? 0) / selections,
          }))
          .sort((a, b) => b.fraction - a.fraction)
      : null;

  return { leader, reward, feedback, segments };
}

// board: w230 h9, 3px gaps, r4 segments. colour is pinned to arm_index, never
// to rank, so an arm keeps its hue as the ordering changes underneath it.
function AllocationBar({ segments }: { segments: Derived["segments"] }) {
  const animate = useAfterFirstData(segments !== null);

  // no equal-split fallback. a uniform bar is not a neutral placeholder — it
  // is the specific claim that the learner has not moved, drawn in the one
  // element on the page whose whole job is to say whether it has. by the time a
  // row draws, the arm stats are in — so no segments means no traffic, which is
  // an answer and gets the inert rail rather than the pulsing one.
  if (!segments) return <EmptyTrack height={9} />;

  return (
    <div className="flex h-[9px] w-full gap-[3px] overflow-hidden">
      {segments.map((seg) => (
        <div
          key={seg.index}
          className={cn(
            "h-full rounded-[4px]",
            animate &&
              "transition-[flex-grow] duration-[var(--motion-data)] ease-entrance",
          )}
          style={{
            backgroundColor: colorForArmIndex(seg.index),
            flexGrow: Math.max(seg.fraction, 0.02),
            flexBasis: 0,
          }}
        />
      ))}
    </div>
  );
}

function PulseMetric({
  label,
  value,
  delta,
  accent,
  deltaTone,
}: {
  label: string;
  value: string;
  delta?: string;
  accent?: boolean;
  /** the Services delta names what is down — the same call ServiceHealthCard
      makes, since "2 / 3" alone doesn't say which */
  deltaTone?: "danger";
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2">
      <span className="truncate text-[14px] text-text-dim">{label}</span>
      <span
        className={cn(
          "font-mono text-[30px] leading-none tracking-[-0.033em] tabular-nums",
          accent ? "text-accent" : "text-text-primary",
        )}
      >
        {value}
      </span>
      {delta && (
        <span
          className={cn(
            "truncate text-[13px]",
            deltaTone === "danger" ? "text-danger" : "text-text-faint",
          )}
        >
          {delta}
        </span>
      )}
    </div>
  );
}

// both column sets open with this cell, unchanged — it is the one part of the
// row that needs no analytics, and the reason the two share a left edge.
function ExperimentIdentityCell({ exp }: { exp: Experiment }) {
  const armCount = exp.pool?.arms?.length ?? 0;

  return (
    <Cell>
      <div className="flex items-center gap-[13px]">
        <AccentDot
          size={8}
          tone={exp.enabled ? "accent" : "faint"}
          active={exp.enabled}
        />
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate text-[15px] font-medium text-text-primary">
            {exp.name}
          </span>
          <span className="truncate text-[13px] text-text-faint">
            {exp.pool?.name ?? "—"} · {armCount} variants
          </span>
        </div>
      </div>
    </Cell>
  );
}

// no `loading` prop any more. the row is only ever drawn once its arm stats are
// in the page's first-paint set, so an absent entry now means what it says —
// that experiment has no events yet — and "—" is the answer, not a placeholder.
function ExperimentRow({
  exp,
  armStats,
}: {
  exp: Experiment;
  armStats: ArmStats[] | undefined;
}) {
  const d = useMemo(() => derive(exp, armStats), [exp, armStats]);

  return (
    <Link href={routes.experimentDetail(exp.id)} className="block">
      <DataRow>
        <ExperimentIdentityCell exp={exp} />
        <Cell width={150}>
          <span className="text-[14px] text-text-secondary">
            {d.leader ?? "—"}
          </span>
        </Cell>
        <Cell width={84} align="right">
          <span className="font-mono text-[15px] tracking-[0.02em] tabular-nums text-text-primary">
            {d.reward === null ? "—" : `${(d.reward * 100).toFixed(2)}%`}
          </span>
        </Cell>
        <Cell width={108} align="right">
          <span className="font-mono text-[15px] tracking-[0.02em] tabular-nums text-text-secondary">
            {compact(d.feedback)}
          </span>
        </Cell>
        <Cell width={230}>
          <AllocationBar segments={d.segments} />
        </Cell>
      </DataRow>
    </Link>
  );
}

// both rails draw a two-line row on a hairline, so their loading state has to
// be that shape too — five `h-8` bars in a `gap-4` column was 40px short per
// row, and the whole rail jumped when the data landed.
function RailSkeleton() {
  return (
    <div className="flex flex-col">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex items-start gap-[13px] border-b border-border-subtle py-3.5 last:border-b-0"
        >
          <Skeleton className="mt-1 size-[7px] shrink-0 rounded-full" />
          <div className="flex min-w-0 flex-1 flex-col gap-[5px]">
            <Skeleton className="h-[15px]" style={{ width: 132 - i * 9 }} />
            <Skeleton className="h-[14px] w-full max-w-[168px]" />
          </div>
        </div>
      ))}
    </div>
  );
}

// the same row, minus everything the insights router feeds
function CoreExperimentRow({ exp }: { exp: Experiment }) {
  return (
    <Link href={routes.experimentDetail(exp.id)} className="block">
      <DataRow>
        <ExperimentIdentityCell exp={exp} />
        <Cell width={190}>
          <span className="truncate text-[12.5px] text-text-secondary">
            {exp.policy}
          </span>
        </Cell>
        <Cell width={120}>
          <span className="text-[12.5px] text-text-dim">{gateSummary(exp)}</span>
        </Cell>
        <Cell width={110}>
          <span
            className={cn(
              "text-[13.5px]",
              exp.enabled ? "text-text-secondary" : "text-text-dim",
            )}
          >
            {exp.enabled ? "Running" : "Paused"}
          </span>
        </Cell>
      </DataRow>
    </Link>
  );
}

// board `APP · OSS · Home (EE disabled)` / Right. the rail is the same frame the
// activity feed uses; only its contents change. it also catches the growth-tier
// tenant who has insights but not the event log, and whose rail is empty today.
function PoolsRail({
  pools,
  expCounts,
}: {
  pools: Pool[];
  expCounts: Map<string, number>;
}) {
  // the rail is a glance, not the Pools page — the board draws five rows and
  // the feed it replaces caps at fourteen. ordered by how much each pool is
  // actually carrying, so truncating cannot hide the busy ones.
  const shown = useMemo(
    () =>
      [...pools]
        .sort(
          (a, b) =>
            (expCounts.get(b.id) ?? 0) - (expCounts.get(a.id) ?? 0) ||
            a.name.localeCompare(b.name),
        )
        .slice(0, RAIL_POOL_LIMIT),
    [pools, expCounts],
  );

  return (
    <aside className="hidden w-[352px] shrink-0 flex-col border-l border-border-subtle px-[22px] py-5 xl:flex">
      <h2 className="text-[17px] font-semibold text-text-primary">Pools</h2>
      <div className="h-3.5" />
      {pools.length === 0 && (
        <p className="text-[13.5px] text-text-faint">No pools yet.</p>
      )}
      <div className="flex flex-col">
        {shown.map((pool) => {
          const experiments = expCounts.get(pool.id) ?? 0;
          return (
            <Link
              key={pool.id}
              href={routes.pools}
              className="flex items-start gap-[13px] border-b border-border-subtle py-3.5 last:border-b-0"
            >
              {/* a pool has no state to report, so the dot is a bullet, not a
                  status light — faint, and drawn flush with the name's top */}
              <AccentDot size={7} tone="faint" />
              <div className="flex min-w-0 flex-1 flex-col gap-[5px]">
                <span className="truncate text-[14px] font-medium text-text-primary">
                  {pool.name}
                </span>
                <span className="truncate text-[13.5px] text-text-dim">
                  {pool.arms.length} {pool.arms.length === 1 ? "variant" : "variants"}
                  {" · "}
                  {experiments} {experiments === 1 ? "experiment" : "experiments"}
                </span>
              </div>
              <span className="shrink-0 text-[12.5px] text-text-faint">→</span>
            </Link>
          );
        })}
      </div>
    </aside>
  );
}

function ActivityFeed({ experiments }: { experiments: Experiment[] }) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.events.list({ limit: 14 }),
    queryFn: () => eventsApi.list({ limit: 14 }),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    experiments.forEach((e) => m.set(e.id, e.name));
    return m;
  }, [experiments]);

  const entries: UnifiedEvent[] = data?.events ?? [];

  return (
    <aside className="hidden w-[352px] shrink-0 flex-col border-l border-border-subtle px-[22px] py-5 xl:flex">
      <h2 className="text-[17px] font-semibold text-text-primary">Activity</h2>
      <div className="h-3.5" />
      {isLoading && <RailSkeleton />}
      {!isLoading && entries.length === 0 && (
        <p className="text-[13.5px] text-text-faint">No activity yet.</p>
      )}
      <div className="flex flex-col">
        {entries.map((e, i) => (
          <div
            key={`${e.resource_id}-${e.timestamp_ms}-${i}`}
            className="flex items-start gap-[13px] border-b border-border-subtle py-3.5 last:border-b-0"
          >
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="truncate text-[14px] font-medium text-text-primary">
                {nameById.get(e.resource_id) ?? e.resource_id.slice(0, 12)}
              </span>
              <span className="truncate text-[13px] text-text-dim">
                {e.name.replace(/[._]/g, " ")}
              </span>
            </div>
            <span className="shrink-0 font-mono text-[11px] text-text-faint">
              {relativeTime(e.timestamp_ms)}
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}

// board `APP · Empty, loading & error states`: "the loading state reserves the
// exact height its content will take so nothing jumps". so this is not a
// stand-in layout — it is Home's own geometry with skeletons where the values
// go, down to the 34px column bar, the 68px rows and the 352px rail.
//
// it is drawn once, for the whole page, and replaced once. the pieces that poll
// (stream depth, service health, activity) are the only things allowed to still
// be moving after it clears.
function HomeSkeleton({ hasInsights }: { hasInsights: boolean }) {
  const pulseCount = hasInsights ? 5 : 4;

  return (
    <div className="flex flex-1 flex-col">
      {/* PageHead: px-7 pb-5 pt-6, 26px title over a 15px meta line */}
      <div className="flex items-end justify-between gap-6 px-7 pb-5 pt-6">
        <div className="flex min-w-0 flex-col gap-[7px]">
          <Skeleton className="h-[26px] w-[232px]" />
          <Skeleton className="h-[15px] w-[176px]" />
        </div>
        <Skeleton className="h-9 w-[158px] shrink-0 rounded-full" />
      </div>

      <div className="flex gap-6 border-b border-border-subtle px-7 pb-[22px] pt-5">
        {Array.from({ length: pulseCount }).map((_, i) => (
          <div key={i} className="flex min-w-0 flex-1 flex-col gap-2">
            <Skeleton className="h-[14px] w-[92px]" />
            <Skeleton className="h-[30px] w-[76px]" />
            <Skeleton className="h-[13px] w-[64px]" />
          </div>
        ))}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          {/* SectionHead: the filter tabs and the search box are chrome, not
              data — they are drawn for real so they do not slide into place */}
          <SectionHead
            title="Active experiments"
            action={<Skeleton className="h-[30px] w-[268px] rounded-md" />}
          />

          <ColumnBar columns={hasInsights ? COLUMNS : CORE_COLUMNS} />

          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="flex h-[68px] items-center gap-[18px] border-b border-border-subtle px-7"
            >
              <div className="flex min-w-0 flex-1 items-center gap-[13px]">
                <Skeleton className="size-[8px] shrink-0 rounded-full" />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <Skeleton className="h-[15px]" style={{ width: 188 - i * 14 }} />
                  <Skeleton className="h-[13px] w-[124px]" />
                </div>
              </div>
              {hasInsights ? (
                <>
                  <Skeleton className="h-[14px] w-[150px]" />
                  <Skeleton className="h-[15px] w-[84px]" />
                  <Skeleton className="h-[15px] w-[108px]" />
                  {/* the allocation column: a flat track, never an equal split */}
                  <SkeletonTrack className="w-[230px]" height={9} />
                </>
              ) : (
                <>
                  <Skeleton className="h-[12.5px] w-[190px]" />
                  <Skeleton className="h-[12.5px] w-[120px]" />
                  <Skeleton className="h-[13.5px] w-[110px]" />
                </>
              )}
            </div>
          ))}

          <div className="flex-1" />
        </div>

        <aside className="hidden w-[352px] shrink-0 flex-col border-l border-border-subtle px-[22px] py-5 xl:flex">
          <Skeleton className="h-[17px] w-[74px]" />
          <div className="h-3.5" />
          <RailSkeleton />
        </aside>
      </div>
    </div>
  );
}

export default function HomePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  // one page, one set of branches — not a fork per deployment shape. Home reads
  // the granted flags rather than `gate()` because absent and locked differ only
  // where there is something to upgrade to, and Home offers nothing: either the
  // columns have data behind them or they would read "—" in every cell.
  const { hasInsights, hasEvents } = useEntitlements();

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filter, setFilter] = useState<FilterTab>("all");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleSearchChange(value: string) {
    setSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedSearch(value), 250);
  }

  // the same limit, and no offset, so that an unfiltered list is key-identical
  // to the workspace totals below and the two share one request. Home has no
  // pagination, so `offset: 0` only ever served to make the keys differ.
  const listParams = useMemo(
    () => ({
      limit: 200,
      ...(debouncedSearch ? { search: debouncedSearch } : {}),
      ...(filter === "active" ? { enabled: true } : {}),
      ...(filter === "paused" ? { enabled: false } : {}),
    }),
    [debouncedSearch, filter],
  );

  const expQuery = useQuery({
    queryKey: queryKeys.experiments.list(listParams),
    queryFn: () => experimentsApi.list(listParams),
    // a search or a tab is a new key, i.e. a new pending query. without this
    // the table empties on every keystroke and the page's one reveal turns
    // back into a flicker per character.
    placeholderData: keepPreviousData,
  });

  // the pulse counts the workspace, the table above is filtered by the search
  // box and the tabs — so they cannot be one query. both keys below are the ones
  // pools/page.tsx already uses, which makes this a shared cache entry rather
  // than a second request.
  const totalsQuery = useQuery({
    queryKey: queryKeys.experiments.list({ limit: 200 }),
    queryFn: () => experimentsApi.list({ limit: 200 }),
  });

  const poolsQuery = useQuery({
    queryKey: queryKeys.pools.list({ limit: 100 }),
    queryFn: () => poolsApi.list({ limit: 100 }),
  });

  const streamQuery = useQuery({
    queryKey: queryKeys.runtime.streamSize,
    queryFn: () => runtime.streamSize(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const health = useServiceHealth();

  const exps = expQuery.data?.experiments ?? [];
  const allExps = totalsQuery.data?.experiments ?? [];
  const allPools = poolsQuery.data?.pools ?? [];
  const totalPools = allPools.length;
  const activeExps = allExps.filter((e) => e.enabled).length;
  const pausedExps = allExps.length - activeExps;
  const totalVariants = allPools.reduce((s, p) => s + p.arms.length, 0);
  const streamLen = streamQuery.data?.len ?? 0;

  const serviceNames = ["redis", "motor", "cortex"] as const;
  const servicesDown = serviceNames.filter((n) => health[n] === "unhealthy");
  const servicesChecking = serviceNames.some((n) => health[n] === "loading");
  const servicesUp = serviceNames.length - servicesDown.length;

  // one pass over the same list the pulse counts — not one request per pool
  const expCountsByPool = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of allExps) m.set(e.pool_id, (m.get(e.pool_id) ?? 0) + 1);
    return m;
  }, [allExps]);

  // 24h throughput across active experiments. the window start rounds to the
  // minute so the key is stable for ~60s of renders.
  const minuteBucket = Math.floor(Date.now() / 60_000);
  const windowStartMs = useMemo(
    () => (minuteBucket * 60_000) - 24 * 60 * 60 * 1000,
    [minuteBucket],
  );

  // both of these were a `useQueries` fanning out one request per experiment —
  // 2N requests that could not even be issued until the experiment list came
  // back, which is what made the page fill in row by row. the workspace
  // endpoint is tenant-scoped, so these go out with the list rather than after
  // it, and the join happens here.
  //
  // two calls, not one, because the two windows are genuinely different: the
  // table's Reward / Feedback / Allocation are lifetime figures, the pulse is
  // the last 24h. same endpoint, same shape, one round trip each.
  const armsQuery = useQuery({
    queryKey: queryKeys.insights.workspaceArms(),
    queryFn: () => insightsApi.getWorkspaceArmStats(),
    enabled: hasInsights,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const pulseQuery = useQuery({
    queryKey: queryKeys.insights.workspaceArms({ start_ms: windowStartMs }),
    queryFn: () => insightsApi.getWorkspaceArmStats({ start_ms: windowStartMs }),
    enabled: hasInsights,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });

  const armStatsByExp = useMemo(() => {
    const map = new Map<string, ArmStats[]>();
    for (const e of armsQuery.data?.experiments ?? []) {
      map.set(e.experiment_id, e.arms);
    }
    return map;
  }, [armsQuery.data]);

  // the pulse counts enabled experiments only, and the window response covers
  // the whole workspace — so the filter is a client-side join against the list
  // rather than a narrower request. `allExps`, not `exps`: the search box and
  // the tabs must not move the workspace figures.
  const pulse = useMemo(() => {
    const enabled = new Set(
      allExps.filter((e) => e.enabled).map((e) => e.id),
    );
    let selections = 0;
    let feedback = 0;
    let rewardWeighted = 0;
    for (const e of pulseQuery.data?.experiments ?? []) {
      if (!enabled.has(e.experiment_id)) continue;
      for (const arm of e.arms) {
        selections += arm.selections;
        feedback += arm.feedback_count;
        // weighted by feedback for the same reason as the per-row figure —
        // avg_reward is a mean over that arm's feedback, not over the pulse.
        if (arm.avg_reward != null) {
          rewardWeighted += arm.avg_reward * arm.feedback_count;
        }
      }
    }
    return {
      selections,
      feedback,
      feedbackRate: selections > 0 ? feedback / selections : null,
      rewardRate: feedback > 0 ? rewardWeighted / feedback : null,
    };
  }, [pulseQuery.data, allExps]);

  const firstName = (user?.name ?? user?.email?.split("@")[0] ?? "").split(
    " ",
  )[0];

  const filterTabs: { key: FilterTab; label: string }[] = [
    { key: "all", label: "All" },
    { key: "active", label: "Active" },
    { key: "paused", label: "Paused" },
  ];

  // Home's first-paint set: what the page *is*. the stream depth, the service
  // health and the activity feed are all polls that move on their own clock
  // anyway — gating the page on them would hold it to the slowest thing on it,
  // and they each keep their own in-place state.
  const ready = usePageReady([
    expQuery,
    totalsQuery,
    poolsQuery,
    armsQuery,
    pulseQuery,
  ]);

  // board `APP · First run · empty console`. a workspace with no experiments
  // gets the quick start rather than four zero-value stat cards and three
  // empty tables. `totalsQuery` is the unfiltered list, so the search box and
  // the tabs cannot put anyone here by accident. `isPending`, not `isLoading`:
  // a paused retry reports `isLoading` false with no data.
  const firstRun =
    !totalsQuery.isPending && !totalsQuery.isError && allExps.length === 0;

  return (
    <PageReveal
      ready={ready}
      skeleton={<HomeSkeleton hasInsights={hasInsights} />}
      className="flex flex-1 flex-col"
    >
      {firstRun ? (
        <FirstRunHome hasPools={totalPools > 0} />
      ) : (
        <>
      <PageHead
        title={firstName ? `${greeting()}, ${firstName}` : greeting()}
        meta={`${activeExps} ${activeExps === 1 ? "experiment" : "experiments"} running · ${totalPools} ${totalPools === 1 ? "pool" : "pools"}`}
        action={
          <Link href={routes.newExperiment()} className={buttonClass()}>
            <Plus size={15} />
            New experiment
          </Link>
        }
      />

      {/* pulse — board draws five. "unique contexts" is deliberately not one of
          them: unique_contexts is per-experiment, so summing it counts a
          context once per experiment it appears in. active experiments is the
          honest fifth. */}
      <div className="flex gap-6 border-b border-border-subtle px-7 pb-[22px] pt-5">
        {hasInsights ? (
          <>
            <PulseMetric
              label="Selections · 24h"
              value={pulse.selections.toLocaleString()}
            />
            <PulseMetric
              label="Reward rate"
              value={
                pulse.rewardRate === null
                  ? "—"
                  : `${(pulse.rewardRate * 100).toFixed(2)}%`
              }
              accent
            />
            <PulseMetric
              label="Feedback rate"
              value={
                pulse.feedbackRate === null
                  ? "—"
                  : `${(pulse.feedbackRate * 100).toFixed(1)}%`
              }
              delta="of selections"
            />
            <PulseMetric
              label="Active experiments"
              value={String(activeExps)}
              delta={`of ${allExps.length}`}
            />
            {/* outside the first-paint set — a 30s poll, so it is the one
                figure allowed to arrive after the reveal */}
            <PulseMetric
              label="Events queued"
              value={streamQuery.isPending ? "—" : streamLen.toLocaleString()}
              delta="draining"
            />
          </>
        ) : (
          /* board `APP · OSS · Home (EE disabled)` / Pulse — the four figures
             that exist without the insights router. */
          <>
            <PulseMetric
              label="Experiments"
              value={String(allExps.length)}
              delta={`${activeExps} running · ${pausedExps} paused`}
            />
            <PulseMetric
              label="Pools"
              value={String(totalPools)}
              delta={`${totalVariants} variants total`}
            />
            <PulseMetric
              label="Services"
              value={servicesChecking ? "—" : `${servicesUp} / ${SERVICE_COUNT}`}
              delta={
                servicesDown.length > 0
                  ? `${servicesDown.join(" · ")} unreachable`
                  : serviceNames.join(" · ")
              }
              deltaTone={servicesDown.length > 0 ? "danger" : undefined}
            />
            <PulseMetric
              label="Events queued"
              value={streamQuery.isPending ? "—" : streamLen.toLocaleString()}
              delta="draining"
            />
          </>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          {/* the OSS board puts a "View all →" in this slot. its only target is
              /experiments, which Home replaced — the filters and the search box
              are what "view all" would have led to. */}
          <SectionHead
            title="Active experiments"
            action={
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1">
                  {filterTabs.map((t) => (
                    <button
                      key={t.key}
                      type="button"
                      onClick={() => setFilter(t.key)}
                      className={cn(
                        "h-[30px] rounded-md px-3 text-[13px] transition-colors",
                        filter === t.key
                          ? "bg-bg-hover font-medium text-text-primary"
                          : "text-text-dim hover:bg-bg-hover hover:text-text-secondary",
                      )}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
                <div className="flex h-[30px] items-center gap-2 rounded-md border border-border-subtle bg-bg-panel px-2.5 transition-colors focus-within:border-border">
                  <Search size={14} className="shrink-0 text-text-faint" />
                  <input
                    type="text"
                    placeholder="Search experiments…"
                    value={search}
                    onChange={(e) => handleSearchChange(e.target.value)}
                    className="w-40 bg-transparent text-[13px] text-text-primary outline-none placeholder:text-text-faint"
                  />
                </div>
              </div>
            }
          />

          <ColumnBar columns={hasInsights ? COLUMNS : CORE_COLUMNS} />

          {/* the row skeleton moved to `HomeSkeleton` — it is the page's, not
              the table's. after the reveal a search keeps its previous rows
              (`keepPreviousData`) rather than emptying the table under the
              cursor, so there is no second loading state here to draw. */}

          {expQuery.isError && (
            <div className="flex flex-1 items-center justify-center py-16">
              <ErrorState
                title="Couldn't load experiments"
                description="The request to the API failed. This is usually transient — nothing has been lost."
                code={apiErrorCode(expQuery.error)}
                onRetry={() => expQuery.refetch()}
              />
            </div>
          )}

          {!expQuery.isError && exps.length === 0 && (
            <div className="flex flex-1 items-center justify-center py-16">
              <EmptyState
                icon={<ExperimentsEmptyIcon />}
                title={
                  debouncedSearch
                    ? "No experiments match that search"
                    : filter !== "all"
                      ? `No ${filter} experiments`
                      : "No experiments yet"
                }
                description={
                  debouncedSearch || filter !== "all"
                    ? "Try a different filter."
                    : "Create one to start serving variants and learning from outcomes."
                }
                primaryAction={
                  debouncedSearch || filter !== "all"
                    ? undefined
                    : {
                        label: "New experiment",
                        href: routes.newExperiment(),
                      }
                }
              />
            </div>
          )}

          {!expQuery.isError &&
            exps.map((exp) =>
              hasInsights ? (
                <ExperimentRow
                  key={exp.id}
                  exp={exp}
                  armStats={armStatsByExp.get(exp.id)}
                />
              ) : (
                <CoreExperimentRow key={exp.id} exp={exp} />
              ),
            )}

          <div className="flex-1" />
        </div>

        {/* the feed is the audit stream — EE build flag and event_log (scale+)
            together. Home draws no gated card, so where
            there is no feed the board fills the rail with pools rather than
            dropping it and letting the table run to the viewport edge. */}
        {hasEvents ? (
          <ActivityFeed experiments={exps} />
        ) : (
          /* pools are in the first-paint set, so by the time this draws they
             are in — unlike the activity feed, which polls and keeps its own */
          <PoolsRail pools={allPools} expCounts={expCountsByPool} />
        )}
      </div>

        </>
      )}
    </PageReveal>
  );
}
