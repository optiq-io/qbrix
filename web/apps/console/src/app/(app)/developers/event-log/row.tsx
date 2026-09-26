"use client";

import { useQuery } from "@tanstack/react-query";
import { DataRow, Cell } from "@qbrix/ui/components/data-table";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { cn } from "@qbrix/ui/lib/utils";
import { events as eventsApi } from "@/lib/api/events";
import { queryKeys } from "@/lib/api/query-keys";
import type { UnifiedEvent } from "@/lib/api/types";
import {
  logTime,
  payloadOf,
  resourceOf,
  streamDot,
  variantOf,
} from "@/lib/events/derive";
import type { NameIndex } from "@/lib/events/derive";

// board `APP · Event Log` / Log: h44 rows on a hairline, columns at 16 gap.
//
// the board's LAT column is not built — nothing records a request duration.
// the ClickHouse selection row is tenant/experiment/request/event id, arm,
// context, timestamp and policy; there is no timing field to read.

// TYPE is 192 rather than the board's 140: the board's sample names were
// `arm.served` and `reward.binary`, but the real ones run to
// `training.batch.completed`, which needs 187px at mono 13 and was clipping.
// the width comes out of PAYLOAD, which flexes.
export const EVENT_COLUMNS = [
  { label: "Time", width: 108 },
  { label: "Stream", width: 108 },
  { label: "Type", width: 192 },
  { label: "Experiment", width: 160 },
  { label: "Variant", width: 164 },
  { label: "Payload" },
];

function DetailPair({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="w-[104px] shrink-0 font-mono text-[12px] text-text-faint">
        {k}
      </span>
      <span className="min-w-0 break-all font-mono text-[12.5px] text-text-secondary">
        {v}
      </span>
    </div>
  );
}

/** the expanded row. for a selection this also pairs it with its feedback —
 *  `/v1/event/selection/{request_id}` is the only place that join exists. */
function EventDetail({ event }: { event: UnifiedEvent }) {
  const requestId =
    typeof event.data?.request_id === "string" ? event.data.request_id : "";
  const isSelection = event.category === "selection";

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.events.selectionDetail(requestId),
    queryFn: () => eventsApi.getSelectionDetail(requestId),
    enabled: isSelection && requestId.length > 0,
    staleTime: 60_000,
  });

  return (
    <div className="flex gap-10 border-b border-border-subtle bg-bg-raised px-7 py-4">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="pb-1 font-mono text-[11px] tracking-[0.145em] text-text-faint">
          EVENT
        </span>
        <DetailPair k="resource_id" v={event.resource_id || "—"} />
        {Object.entries(event.data ?? {}).map(([k, v]) => (
          <DetailPair key={k} k={k} v={String(v)} />
        ))}
      </div>

      {isSelection && (
        <div className="flex w-[360px] shrink-0 flex-col gap-1.5">
          <span className="pb-1 font-mono text-[11px] tracking-[0.145em] text-text-faint">
            PAIRED FEEDBACK
          </span>
          {isLoading ? (
            <Skeleton className="h-4 w-40" />
          ) : data?.feedback ? (
            <>
              <DetailPair k="reward" v={String(data.feedback.reward)} />
              <DetailPair k="at" v={logTime(data.feedback.timestamp_ms)} />
            </>
          ) : (
            <span className="text-[13px] text-text-faint">
              No feedback recorded for this selection
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function EventRow({
  event,
  names,
  expanded,
  onToggle,
}: {
  event: UnifiedEvent;
  names: NameIndex;
  expanded: boolean;
  onToggle: () => void;
}) {
  const resource = resourceOf(event, names);
  const variant = variantOf(event, names);

  return (
    <div className="flex flex-col">
      {/* a <button> may not wrap the row's block content, so the row itself
          carries the role and its own key handling */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
        className="outline-none focus-visible:bg-bg-hover"
      >
        <DataRow
          height={44}
          gap={16}
          className={cn(
            "cursor-pointer transition-colors hover:bg-bg-hover",
            expanded && "bg-bg-hover",
          )}
        >
          <Cell width={108}>
            <span className="font-mono text-[13px] text-text-faint">
              {logTime(event.timestamp_ms)}
            </span>
          </Cell>

          <Cell width={108}>
            <span className="flex items-center gap-[9px]">
              <span
                className={cn(
                  "size-[7px] shrink-0 rounded-full",
                  streamDot(event.category),
                )}
              />
              <span className="truncate text-[14px] text-text-secondary">
                {event.category}
              </span>
            </span>
          </Cell>

          <Cell width={192}>
            <span className="truncate font-mono text-[13px] text-text-secondary">
              {event.name}
            </span>
          </Cell>

          <Cell width={160}>
            <span
              className={cn(
                "truncate text-[14px]",
                resource.resolved ? "text-text-primary" : "text-text-faint",
              )}
            >
              {resource.text}
            </span>
          </Cell>

          <Cell width={164}>
            <span className="truncate text-[14px] text-text-secondary">
              {variant ?? "—"}
            </span>
          </Cell>

          <Cell>
            <span className="truncate font-mono text-[13px] text-text-dim">
              {payloadOf(event)}
            </span>
          </Cell>
        </DataRow>
      </div>

      {expanded && <EventDetail event={event} />}
    </div>
  );
}
