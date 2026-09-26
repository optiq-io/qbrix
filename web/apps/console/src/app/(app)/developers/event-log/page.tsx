"use client";

import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { PageHead } from "@qbrix/ui/components/page-head";
import { ColumnBar } from "@qbrix/ui/components/data-table";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { cn } from "@qbrix/ui/lib/utils";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { events as eventsApi } from "@/lib/api/events";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { useEntitlements, useFeatureRoute } from "@/lib/entitlements";
import { FeatureGate } from "@/lib/edition";
import { buildNameIndex, streamDot } from "@/lib/events/derive";
import { EVENT_COLUMNS, EventRow } from "./row";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes, docsUrl } from "@/config/routes";
import { ErrorState } from "@qbrix/ui/components/error-state";
import { EmptyState } from "@qbrix/ui/components/empty-state";
import { EventsEmptyIcon } from "@qbrix/ui/components/empty-icons";
import { apiErrorCode } from "@/lib/api/handle-error";

// board `APP · Event Log`. head + filters + a log table, replacing the
// terminal-glyph list this page used to be.
//
// not built: the board's `LAT` column (nothing records a request duration) and
// `Export` (no endpoint, same call as Insights).
//
// kept although the board does not draw them, because they exist today and
// work: the time-range filter, and row expansion into the paired-feedback
// detail that `/v1/event/selection/{id}` is the only source for.

const CATEGORIES = ["all", "feedback", "selection", "audit"] as const;
type Category = (typeof CATEGORIES)[number];

const RANGES = [
  { label: "15m", ms: 15 * 60_000 },
  { label: "1h", ms: 60 * 60_000 },
  { label: "6h", ms: 6 * 60 * 60_000 },
  { label: "24h", ms: 24 * 60 * 60_000 },
];

const PAGE_SIZE = 200;
// the API caps at 500, so a busier minute than that cannot be counted exactly
const COUNT_CAP = 500;

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
      {dot && (
        <span className={cn("size-[7px] shrink-0 rounded-full", dot)} />
      )}
      {children}
    </button>
  );
}

export default function EventLogPage() {
  return (
    <GuardedRoute surface="event-log" backHref={routes.home} backLabel="Back to home">
      <EventLogContent />
    </GuardedRoute>
  );
}

function EventLogContent() {
  const { hasEvents } = useEntitlements();
  useFeatureRoute("event_log");

  const [category, setCategory] = useState<Category>("all");
  const [range, setRange] = useState(RANGES[3]);
  const [experimentId, setExperimentId] = useState<string>("");
  const [live, setLive] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  const experimentsQuery = useQuery({
    queryKey: queryKeys.experiments.list({ limit: 200 }),
    queryFn: () => experimentsApi.list({ limit: 200 }),
    enabled: hasEvents,
  });
  const experimentList = experimentsQuery.data;

  const experiments = useMemo(
    () => experimentList?.experiments ?? [],
    [experimentList],
  );
  const names = useMemo(() => buildNameIndex(experiments), [experiments]);

  // the window is recomputed per poll on purpose — a fixed `now` would freeze
  // the log at the moment the page opened
  const listParams = useMemo(
    () => ({
      ...(category !== "all" ? { category } : {}),
      ...(experimentId ? { resource_id: experimentId } : {}),
      limit: PAGE_SIZE,
    }),
    [category, experimentId],
  );

  const eventsQuery = useQuery({
    queryKey: queryKeys.events.list({ ...listParams, start_ms: range.ms }),
    queryFn: () =>
      eventsApi.list({ ...listParams, start_ms: Date.now() - range.ms }),
    enabled: hasEvents,
    refetchInterval: live ? 5_000 : false,
    // the filters make a new key; keeping the previous page means changing a
    // filter re-renders the table rather than emptying it
    placeholderData: keepPreviousData,
  });
  const { data, isError, error, refetch } = eventsQuery;

  const minuteQuery = useQuery({
    queryKey: queryKeys.events.list({ limit: COUNT_CAP, start_ms: 60_000 }),
    queryFn: () =>
      eventsApi.list({ limit: COUNT_CAP, start_ms: Date.now() - 60_000 }),
    enabled: hasEvents,
    refetchInterval: live ? 10_000 : false,
  });
  const minute = minuteQuery.data;

  // the experiment names resolve the resource column and fill the filter, and
  // the per-minute count sits in the header — all three landed separately.
  const ready = usePageReady([experimentsQuery, eventsQuery, minuteQuery]);

  const rows = data?.events ?? [];
  const filtered = category !== "all" || experimentId !== "";

  const throughput = useMemo(() => {
    if (!minute) return null;
    const n = minute.events.length;
    // a capped count is never singular, so only an exact 1 takes "event"
    const noun = n === 1 ? "event" : "events";
    const count = n >= COUNT_CAP ? `${COUNT_CAP}+` : n.toLocaleString();
    return `${count} ${noun}`;
  }, [minute]);

  if (!hasEvents) return <FeatureGate surface="event-log" />;

  return (
    <div className="flex flex-1 flex-col">
      <PageHead
        className="pb-4"
        title="Event log"
        adornments={
          <span
            className={cn(
              "flex h-7 shrink-0 items-center gap-[7px] rounded-full px-[11px] text-[13.5px] font-medium",
              live ? "bg-positive/10 text-positive" : "bg-bg-hover text-text-dim",
            )}
          >
            <span
              className={cn(
                "size-[7px] rounded-full",
                live ? "bg-positive" : "bg-text-faint",
              )}
            />
            {live ? "Live" : "Paused"}
          </span>
        }
        action={
          <span className="text-[14px] text-text-dim">
            {throughput === null ? " " : `${throughput} in the last minute`}
          </span>
        }
      />

      <div className="flex items-center gap-2.5 px-7 pb-4">
        <label className="flex h-9 w-[340px] shrink-0 items-center gap-2.5 rounded-full bg-white/[0.04] px-3.5">
          <Search size={15} className="shrink-0 text-text-faint" />
          <select
            value={experimentId}
            onChange={(e) => setExperimentId(e.target.value)}
            aria-label="Filter by experiment"
            className="w-full cursor-pointer appearance-none bg-transparent font-mono text-[13.5px] text-text-secondary outline-none"
          >
            <option value="">all experiments</option>
            {experiments.map((exp) => (
              <option key={exp.id} value={exp.id}>
                experiment:{exp.name}
              </option>
            ))}
          </select>
        </label>

        {CATEGORIES.map((c) => (
          <Chip
            key={c}
            active={category === c}
            dot={c === "all" ? undefined : streamDot(c)}
            onClick={() => setCategory(c)}
          >
            {c}
          </Chip>
        ))}

        <div className="flex flex-1 items-center justify-end gap-2.5">
          {RANGES.map((r) => (
            <Chip
              key={r.label}
              active={range.label === r.label}
              onClick={() => setRange(r)}
            >
              {r.label}
            </Chip>
          ))}
          {/* the board draws a `Live` chip and an `Autoscroll on` label; the
              list is newest-first and not a pinned viewport, so both describe
              the same thing — whether polling is running */}
          <button
            type="button"
            aria-pressed={live}
            onClick={() => setLive((v) => !v)}
            className="shrink-0 pl-1 text-[13.5px] text-text-faint transition-colors hover:text-text-secondary"
          >
            Autoscroll {live ? "on" : "off"}
          </button>
        </div>
      </div>

      <ColumnBar columns={EVENT_COLUMNS} gap={16} />

      {!ready ? (
        [0, 1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="flex h-11 items-center border-b border-border-subtle px-7"
          >
            <Skeleton className="h-3.5 w-full" />
          </div>
        ))
      ) : isError ? (
        <ErrorState
          title="Couldn't load the event log"
          description="The request to the API failed. This is usually transient — nothing has been lost."
          code={apiErrorCode(error)}
          onRetry={() => refetch()}
        />
      ) : rows.length === 0 ? (
        /* two different empties: a filter that matched nothing is the user's
           doing and needs no onboarding copy, an unfiltered stream with nothing
           on it is the board's `EVENT LOG · EMPTY`. */
        filtered ? (
          <EmptyState
            icon={<EventsEmptyIcon />}
            title="Nothing matched these filters"
            description={`No events in the last ${range.label} for this category and experiment. Widen the range or clear the filters.`}
          />
        ) : (
          <EmptyState
            icon={<EventsEmptyIcon />}
            title="Nothing on the stream yet"
            description="Every selection, feedback and audit event lands here the moment it happens. This fills itself once your app starts calling."
            secondaryAction={{
              label: "Read the quickstart",
              href: docsUrl("getting-started"),
              external: true,
            }}
          />
        )
      ) : (
        rows.map((event) => {
          const key = `${event.timestamp_ms}:${event.name}:${event.resource_id}`;
          return (
            <EventRow
              key={key}
              event={event}
              names={names}
              expanded={expanded === key}
              onToggle={() => setExpanded(expanded === key ? null : key)}
            />
          );
        })
      )}
    </div>
  );
}
