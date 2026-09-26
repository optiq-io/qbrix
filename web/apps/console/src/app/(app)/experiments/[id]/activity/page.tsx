"use client";

import { useCallback, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnBar } from "@qbrix/ui/components/data-table";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { EmptyState } from "@qbrix/ui/components/empty-state";
import { ErrorState } from "@qbrix/ui/components/error-state";
import { EventsEmptyIcon } from "@qbrix/ui/components/empty-icons";
import { cn } from "@qbrix/ui/lib/utils";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { apiErrorCode } from "@/lib/api/handle-error";
import { events as eventsApi } from "@/lib/api/events";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { auth as authApi } from "@/lib/api/auth";
import { buildActorIndex, buildNameIndex, eventKey, streamDot } from "@/lib/events/derive";
import { useEntitlements, useFeatureRoute } from "@/lib/entitlements";
import { FeatureGate } from "@/lib/edition";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes, docsUrl } from "@/config/routes";
import type { UnifiedEvent, UnifiedEventListResponse } from "@/lib/api/types";
import { useHeaderTool } from "../header-actions";
import { ACTIVITY_COLUMNS, ActivityRow } from "./row";

// board `APP · Experiment / Activity`.
//
// the workspace event log scoped to one experiment. it is a tab rather than a
// link into `/developers/event-log?experiment=` because you arrive for a
// different reason — auditing one config's history, not watching throughput —
// and the columns follow: EXPERIMENT is constant here and gives up its place to
// ACTOR, which only audit rows carry.
//
// there is no range control. the stream chips are the instrument, and an audit
// trail wants all of history rather than a window: `training.batch.completed`
// arrives every few seconds while the config change you came for was in March.
//
// not built: a per-hour density band. the feed caps at 500 rows a request, so
// any chart drawn from it would describe the page rather than the experiment.

const CATEGORIES = ["all", "selection", "feedback", "audit"] as const;
type Category = (typeof CATEGORIES)[number];

// the endpoint caps at 500; 200 matches the event log and keeps a page of rows
// well past the fold on a laptop
const PAGE_SIZE = 200;

const POLL_MS = 5_000;

function Chip({
  active,
  dot,
  children,
  onClick,
}: {
  active: boolean;
  dot?: string;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex h-9 shrink-0 items-center gap-[9px] rounded-full px-3.5 text-[14px] transition-colors",
        active
          ? "bg-white/[0.07] text-text-primary"
          : "border border-border-subtle text-text-dim hover:text-text-secondary",
      )}
    >
      {dot && <span className={cn("size-[7px] shrink-0 rounded-full", dot)} />}
      {children}
    </button>
  );
}

/** the tab's own control, mounted in the page head left of Pause. it is a
 *  toggle and not a status chip: the head already carries one green pill for
 *  the experiment's own state, and a second would read as a second fact about
 *  the experiment rather than a control over the page. */
function LiveToggle({ live, onToggle }: { live: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={live}
      onClick={onToggle}
      className={cn(
        "flex h-9 shrink-0 items-center gap-[9px] rounded-full px-4 text-[14.5px] font-medium transition-colors",
        live
          ? "bg-white/[0.07] text-text-primary"
          : "border border-border-subtle text-text-dim hover:text-text-secondary",
      )}
    >
      <span
        className={cn(
          "size-[7px] shrink-0 rounded-full",
          live ? "bg-positive" : "bg-text-faint",
        )}
      />
      {live ? "Live" : "Paused"}
    </button>
  );
}

export default function ActivityPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <GuardedRoute
      surface="experiment.activity"
      backHref={routes.experimentOverview(id)}
      overviewHref={routes.experimentOverview(id)}
    >
      <ActivityContent />
    </GuardedRoute>
  );
}

function ActivityContent() {
  const params = useParams();
  const experimentId = params.id as string;
  const { hasEvents } = useEntitlements();
  useFeatureRoute("event_log");
  const queryClient = useQueryClient();

  const [category, setCategory] = useState<Category>("all");
  const [live, setLive] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  // same key as the layout and every sibling tab — one fetch serves all of them.
  // the pool's arms are what resolve the VARIANT column: a feedback event
  // carries `arm_index` and no name at all.
  const experimentQuery = useQuery({
    queryKey: queryKeys.experiments.detail(experimentId),
    queryFn: () => experimentsApi.get(experimentId),
  });
  const experiment = experimentQuery.data;

  // shared key with the Members settings tab. `/auth/workspace/members` is open
  // to every role, so this is not an admin-only column.
  const membersQuery = useQuery({
    queryKey: queryKeys.workspace.members(),
    queryFn: () => authApi.listMembers(),
    enabled: hasEvents,
    staleTime: 5 * 60_000,
  });

  const names = useMemo(
    () => buildNameIndex(experiment ? [experiment] : []),
    [experiment],
  );
  const actors = useMemo(
    () => buildActorIndex(membersQuery.data?.users ?? []),
    [membersQuery.data],
  );

  // memoized because `toggleLive` closes over it, and that in turn is what
  // keeps the head's tool node stable — `useHeaderTool` re-registers on every
  // new node it is handed
  const listKey = useMemo(
    () =>
      queryKeys.events.experimentActivity(experimentId, {
        category: category === "all" ? undefined : category,
        limit: PAGE_SIZE,
      }),
    [experimentId, category],
  );

  // how many pages are loaded, read off the client because the query below has
  // not been declared yet. the query re-renders this component whenever its data
  // changes, so this recomputes with it.
  const pageCount =
    queryClient.getQueryData<{ pages: unknown[] }>(listKey)?.pages.length ?? 1;

  // "tailing" and not simply `live`: the query cache is persisted to
  // sessionStorage, so a reload restores however many pages you had paged back
  // to while `live` resets to its default, and polling would then refetch every
  // one of them on a timer. the tail is the first page or nothing.
  const tailing = live && pageCount <= 1;

  // keyset paging, not offset: the feed grows at the head, so an offset window
  // shifts under every page and repeats rows already shown. each page asks for
  // everything strictly older than the last row it has.
  //
  // the bound is `+1` because `until_ms` is exclusive and two events can share
  // a millisecond — a tight bound would drop the rest of that millisecond
  // silently, which is the one failure an audit trail must not have. the
  // overlap it admits instead is removed by `eventKey` below.
  const feedQuery = useInfiniteQuery({
    queryKey: listKey,
    queryFn: ({ pageParam }) =>
      eventsApi.experimentActivity(experimentId, {
        ...(category !== "all" ? { category } : {}),
        ...(pageParam !== null ? { until_ms: pageParam } : {}),
        limit: PAGE_SIZE,
      }),
    initialPageParam: null as number | null,
    getNextPageParam: (
      lastPage: UnifiedEventListResponse,
      _pages: UnifiedEventListResponse[],
      lastParam: number | null,
    ) => {
      if (lastPage.events.length < PAGE_SIZE) return undefined;
      const oldest = lastPage.events[lastPage.events.length - 1];
      const next = oldest.timestamp_ms + 1;
      // bounds must strictly decrease. a whole page inside one millisecond
      // would otherwise ask for the same window forever, and "Load more" would
      // never stop being offered.
      if (lastParam !== null && next >= lastParam) return undefined;
      return next;
    },
    enabled: hasEvents,
    refetchInterval: tailing ? POLL_MS : false,
  });

  const { data, isError, error, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    feedQuery;

  // the experiment names the variants, the roster names the actors, and the feed
  // is the page — all three land separately, and the page commits once
  const ready = usePageReady([experimentQuery, membersQuery, feedQuery]);

  const rows = useMemo(() => {
    const seen = new Set<string>();
    const out: { key: string; event: UnifiedEvent }[] = [];
    for (const page of data?.pages ?? []) {
      for (const event of page.events) {
        const key = eventKey(event);
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ key, event });
      }
    }
    return out;
  }, [data]);

  // paging leaves the tail: polling would refetch every loaded page every five
  // seconds, and the rows you walked back to would keep jumping under you.
  const loadMore = useCallback(() => {
    setLive(false);
    fetchNextPage();
  }, [fetchNextPage]);

  // turning it back on returns to the tail — the pages below are dropped rather
  // than kept and re-polled.
  const toggleLive = useCallback(() => {
    if (tailing) {
      setLive(false);
      return;
    }
    queryClient.setQueryData(
      listKey,
      (old: { pages: unknown[]; pageParams: unknown[] } | undefined) =>
        old && old.pages.length > 1
          ? { pages: old.pages.slice(0, 1), pageParams: old.pageParams.slice(0, 1) }
          : old,
    );
    setLive(true);
  }, [tailing, queryClient, listKey]);

  const tool = useMemo(
    () => <LiveToggle live={tailing} onToggle={toggleLive} />,
    [tailing, toggleLive],
  );
  useHeaderTool(tool);

  const filtered = category !== "all";

  if (!ready) {
    return (
      <div className="flex flex-col">
        <div className="flex items-center gap-2.5 px-7 pb-4">
          <Skeleton className="h-9 w-[280px] rounded-full" />
        </div>
        <ColumnBar columns={ACTIVITY_COLUMNS} gap={16} />
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <div
            key={i}
            className="flex h-11 items-center border-b border-border-subtle px-7"
          >
            <Skeleton className="h-3.5 w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (!hasEvents) return <FeatureGate surface="experiment.activity" />;

  return (
    <div className="flex flex-1 flex-col">
      {/* the board runs the chips flush under the tab bar's hairline: the tab
          pills are h36 inside an h50 row, so the rhythm is already there */}
      <div className="flex items-center gap-2.5 px-7 pb-4">
        {CATEGORIES.map((c) => (
          <Chip
            key={c}
            active={category === c}
            dot={c === "all" ? undefined : streamDot(c)}
            onClick={() => {
              setCategory(c);
              setExpanded(null);
              // a new filter is a new tail
              setLive(true);
            }}
          >
            {c}
          </Chip>
        ))}

        <span className="ml-auto text-[13.5px] text-text-faint">Newest first</span>
      </div>

      <ColumnBar columns={ACTIVITY_COLUMNS} gap={16} />

      {isError ? (
        <ErrorState
          title="Couldn't load this experiment's activity"
          description="The request to the API failed. This is usually transient — nothing has been lost."
          code={apiErrorCode(error)}
          onRetry={() => refetch()}
        />
      ) : rows.length === 0 ? (
        /* two different empties: a filter that matched nothing is the user's own
           doing and needs no onboarding copy, an unfiltered feed with nothing on
           it is the board's `ACTIVITY · EMPTY`. */
        filtered ? (
          <EmptyState
            icon={<EventsEmptyIcon />}
            title="Nothing matched these filters"
            description={`No ${category} events on this experiment. Clear the filter to see everything it has done.`}
          />
        ) : (
          <EmptyState
            icon={<EventsEmptyIcon />}
            title="No activity on this experiment yet"
            description="Every selection, reward and configuration change on this experiment lands here, newest first. It fills the moment your app calls select."
            secondaryAction={{
              label: "Read the quickstart",
              href: docsUrl("getting-started"),
              external: true,
            }}
          />
        )
      ) : (
        <>
          {rows.map(({ key, event }) => (
            <ActivityRow
              key={key}
              event={event}
              names={names}
              actors={actors}
              expanded={expanded === key}
              onToggle={() => setExpanded(expanded === key ? null : key)}
            />
          ))}

          <div className="flex h-14 items-center gap-3 px-7">
            <span className="text-[13.5px] text-text-faint">
              Showing {rows.length.toLocaleString()}{" "}
              {rows.length === 1 ? "event" : "events"}
              {!tailing && " · live paused while you page back"}
            </span>

            {hasNextPage && (
              <button
                type="button"
                onClick={loadMore}
                disabled={isFetchingNextPage}
                className="ml-auto flex h-[34px] shrink-0 items-center rounded-[17px] border border-border-subtle px-4 text-[14px] font-medium text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary disabled:pointer-events-none disabled:opacity-50"
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
