"use client";

import { useQuery } from "@tanstack/react-query";
import { DataRow, Cell } from "@qbrix/ui/components/data-table";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { cn } from "@qbrix/ui/lib/utils";
import { events as eventsApi } from "@/lib/api/events";
import { queryKeys } from "@/lib/api/query-keys";
import {
  actorOf,
  logTime,
  payloadOf,
  streamDot,
  variantOf,
} from "@/lib/events/derive";
import type { ActorIndex, NameIndex } from "@/lib/events/derive";
import type { UnifiedEvent } from "@/lib/api/types";

// board `APP · Experiment / Activity`.
//
// the same h44 log row as the workspace event log, minus its EXPERIMENT column
// and plus ACTOR. that swap is the whole reason this is a tab and not a link:
// the experiment is constant here, so naming it in every row buys nothing,
// while `actor_id` — which only audit rows carry — answers the question you
// came to an experiment's history to ask.
//
// TYPE is 204 rather than the event log's 192: this feed carries the training
// lifecycle, and `training.batch.completed` wraps below that at mono 13 with
// the 0.3 tracking the boards use.

export const ACTIVITY_COLUMNS = [
  { label: "Time", width: 100 },
  { label: "Stream", width: 104 },
  { label: "Type", width: 204 },
  { label: "Variant", width: 150 },
  { label: "Actor", width: 132 },
  { label: "Detail" },
];

// the actor has its own column, so leaving it in the payload prints it twice
const PAYLOAD_OMIT = ["actor_id"];

function DetailPair({ k, v, keyWidth }: { k: string; v: string; keyWidth: number }) {
  return (
    <div className="flex gap-3">
      <span
        className="shrink-0 font-mono text-[12px] text-text-faint"
        style={{ width: keyWidth }}
      >
        {k}
      </span>
      <span className="min-w-0 break-all font-mono text-[12.5px] text-text-secondary">
        {v}
      </span>
    </div>
  );
}

function DetailColumn({
  title,
  children,
  width,
}: {
  title: string;
  children: React.ReactNode;
  width?: number;
}) {
  return (
    <div
      className={cn("flex flex-col gap-1.5", width === undefined && "min-w-0 flex-1")}
      style={width !== undefined ? { width } : undefined}
    >
      <span className="pb-1 font-mono text-[11px] tracking-[0.145em] text-text-faint">
        {title}
      </span>
      {children}
    </div>
  );
}

/** the payload half of an expanded row.
 *
 *  audit nests its detail as a JSON *string* under `payload`; flattening it is
 *  the only way the change is readable. it names the fields that changed and
 *  never their values — `experiment.updated` publishes `{"changed_fields": [...]}`
 *  and nothing more — so the panel says so rather than implying a diff it does
 *  not have. */
function AuditPayload({ event }: { event: UnifiedEvent }) {
  const raw = event.data?.payload;
  let parsed: Record<string, unknown> = {};

  if (typeof raw === "string" && raw) {
    try {
      const value = JSON.parse(raw);
      if (value && typeof value === "object") parsed = value as Record<string, unknown>;
    } catch {
      parsed = { payload: raw };
    }
  } else if (raw && typeof raw === "object") {
    parsed = raw as Record<string, unknown>;
  }

  const pairs = Object.entries(parsed);

  return (
    <DetailColumn title="Payload">
      {pairs.length === 0 ? (
        <span className="text-[13px] text-text-faint">
          This event carries no payload
        </span>
      ) : (
        pairs.map(([k, v]) => (
          <DetailPair key={k} k={k} v={JSON.stringify(v)} keyWidth={128} />
        ))
      )}
      <span className="pt-2 text-[12px] leading-[1.5] text-text-faint">
        An audit payload names the fields that changed, never their values — the
        console cannot show a before and after it was never sent.
      </span>
    </DetailColumn>
  );
}

/** the feedback half of an expanded selection. `/v1/event/selection/{id}` is
 *  the only place that join exists. */
function PairedFeedback({ requestId }: { requestId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.events.selectionDetail(requestId),
    queryFn: () => eventsApi.getSelectionDetail(requestId),
    enabled: requestId.length > 0,
    staleTime: 60_000,
  });

  return (
    <DetailColumn title="Paired feedback">
      {isLoading ? (
        <Skeleton className="h-4 w-40" />
      ) : data?.feedback ? (
        <>
          <DetailPair
            k="reward"
            v={String(data.feedback.reward)}
            keyWidth={104}
          />
          <DetailPair
            k="at"
            v={logTime(data.feedback.timestamp_ms)}
            keyWidth={104}
          />
        </>
      ) : (
        <span className="text-[13px] text-text-faint">
          No feedback recorded for this selection
        </span>
      )}
    </DetailColumn>
  );
}

function ActivityDetail({ event }: { event: UnifiedEvent }) {
  const requestId =
    typeof event.data?.request_id === "string" ? event.data.request_id : "";

  return (
    <div className="flex gap-10 border-b border-border-subtle bg-bg-raised px-7 py-4">
      <DetailColumn title="Event" width={480}>
        <DetailPair
          k="resource_type"
          v={
            typeof event.data?.resource_type === "string"
              ? event.data.resource_type
              : "experiment"
          }
          keyWidth={128}
        />
        <DetailPair k="resource_id" v={event.resource_id || "—"} keyWidth={128} />
        {typeof event.data?.context_id === "string" && (
          <DetailPair k="context_id" v={event.data.context_id} keyWidth={128} />
        )}
        <DetailPair
          k="timestamp_ms"
          v={String(event.timestamp_ms)}
          keyWidth={128}
        />
        {/* last because it is the only long one — a ~200-char signed token that
            wraps to six lines and would otherwise push every short field down */}
        {requestId && (
          <DetailPair k="request_id" v={requestId} keyWidth={128} />
        )}
      </DetailColumn>

      {event.category === "audit" ? (
        <AuditPayload event={event} />
      ) : event.category === "selection" ? (
        <PairedFeedback requestId={requestId} />
      ) : (
        <DetailColumn title="Payload">
          <span className="break-all font-mono text-[12.5px] text-text-secondary">
            {payloadOf(event, PAYLOAD_OMIT)}
          </span>
        </DetailColumn>
      )}
    </div>
  );
}

export function ActivityRow({
  event,
  names,
  actors,
  expanded,
  onToggle,
}: {
  event: UnifiedEvent;
  names: NameIndex;
  actors: ActorIndex;
  expanded: boolean;
  onToggle: () => void;
}) {
  const variant = variantOf(event, names);
  const actor = actorOf(event, actors);

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
          <Cell width={100}>
            <span className="font-mono text-[13px] text-text-faint">
              {logTime(event.timestamp_ms)}
            </span>
          </Cell>

          <Cell width={104}>
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

          <Cell width={204}>
            {/* an audit name is the whole content of the row; traffic names are
                two constants repeating down the page, so they sit back a tier */}
            <span
              className={cn(
                "truncate font-mono text-[13px]",
                event.category === "audit"
                  ? "text-text-primary"
                  : "text-text-secondary",
              )}
            >
              {event.name}
            </span>
          </Cell>

          <Cell width={150}>
            <span
              className={cn(
                "truncate text-[14px]",
                variant ? "text-text-secondary" : "text-text-faint",
              )}
            >
              {variant ?? "—"}
            </span>
          </Cell>

          <Cell width={132}>
            <span
              className={cn(
                "truncate text-[13.5px]",
                actor === null
                  ? "text-text-faint"
                  : actor.resolved
                    ? "text-text-dim"
                    : "font-mono text-text-faint",
              )}
            >
              {actor?.text ?? "—"}
            </span>
          </Cell>

          <Cell>
            <span className="truncate font-mono text-[13px] text-text-dim">
              {payloadOf(event, PAYLOAD_OMIT)}
            </span>
          </Cell>
        </DataRow>
      </div>

      {expanded && <ActivityDetail event={event} />}
    </div>
  );
}
