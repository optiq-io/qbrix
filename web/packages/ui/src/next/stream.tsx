"use client";

import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { GitMerge } from "lucide-react";
import { cn } from "../lib/utils";
import { StateBadge, StateDot, type State } from "./state";

export type StreamLane = {
  key: string;
  name: string;
  state: State;
  /** decisions per interval, oldest first. each lane scales to its own maximum, so a quiet loop's gap still shows */
  pulse: number[];
  /** already formatted: "38 / s" */
  rate: string;
  /** already formatted: "outcomes 99.1% learned", "paused · answering with Relevance" */
  outcomes: string;
  paused?: boolean;
};

export function StreamLanes({
  lanes,
  selected,
  onSelect,
  className,
}: {
  lanes: StreamLane[];
  selected?: string;
  onSelect?: (lane: StreamLane) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {lanes.map((lane) => (
        <Lane key={lane.key} lane={lane} selected={lane.key === selected} onSelect={onSelect} />
      ))}
    </div>
  );
}

function Lane({
  lane,
  selected,
  onSelect,
}: {
  lane: StreamLane;
  selected: boolean;
  onSelect?: (lane: StreamLane) => void;
}) {
  const className = cn(
    "grid min-h-[30px] w-full grid-cols-[170px_minmax(0,1fr)_80px_170px] items-center gap-3 rounded-n-control px-2 py-1 text-left",
    selected && "bg-n-fill-2",
    onSelect && "transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-n-ink",
    onSelect && !selected && "hover:bg-n-fill-1",
  );
  const body = (
    <>
      <span className="flex min-w-0 items-center gap-2">
        <StateDot state={lane.state} className="size-[7px]" />
        <span className={cn("n-meta truncate text-n-text-1", selected && "font-semibold")}>{lane.name}</span>
      </span>
      <Pulse values={lane.pulse} tone={selected ? "bg-n-ink" : lane.paused ? "bg-n-viz-3" : "bg-n-viz-2"} />
      <span className="n-label font-normal tabular-nums text-n-text-2">{lane.rate}</span>
      <span className={cn("n-label font-normal tabular-nums", lane.paused ? "text-n-part-fg" : "text-n-text-2")}>
        {lane.outcomes}
      </span>
    </>
  );

  if (!onSelect) return <div className={className}>{body}</div>;
  return (
    <button type="button" aria-pressed={selected} onClick={() => onSelect(lane)} className={className}>
      {body}
    </button>
  );
}

const Pulse = memo(function Pulse({ values, tone }: { values: number[]; tone: string }) {
  const max = Math.max(...values, 1);
  return (
    <span aria-hidden className="flex h-[22px] min-w-0 items-end gap-px">
      {values.map((value, index) => (
        <span
          key={index}
          className={cn("min-w-0 flex-1", value > 0 && tone)}
          style={{ height: value > 0 ? `max(1px, ${(value / max) * 100}%)` : 0 }}
        />
      ))}
    </span>
  );
});

export type OutcomeState = "waiting" | "learned" | "late" | "sealed" | "unattributed" | "invalid";

const OUTCOME: Record<OutcomeState, { label: string; state?: State }> = {
  waiting: { label: "Waiting" },
  learned: { label: "Learned", state: "ok" },
  late: { label: "Late", state: "part" },
  sealed: { label: "Sealed" },
  unattributed: { label: "Unattributed", state: "no" },
  invalid: { label: "Invalid", state: "no" },
};

export type StreamDecision = {
  kind: "decision";
  key: string;
  /** already formatted: "14:02:11.482", "14 Oct 13:40" */
  decided: string;
  /** absent for an outcome no decision claims */
  option?: string;
  unit: string;
  why?: string;
  outcome: { state: OutcomeState; note?: string };
};

export type StreamMarker = {
  kind: "marker";
  key: string;
  label: string;
  href?: string;
};

export type StreamRow = StreamDecision | StreamMarker;

const ROW_HEIGHT: Record<StreamRow["kind"], number> = { decision: 32, marker: 22 };
const OVERSCAN = 10;
const COLUMNS = "grid grid-cols-[84px_130px_minmax(0,1fr)_84px_176px] items-center gap-3 px-2";
const STRETCHED =
  "absolute inset-0 rounded-n-control focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-n-ink";

function firstAtOrAfter(offsets: number[], position: number) {
  let low = 0;
  let high = offsets.length - 1;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (offsets[middle] < position) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** newest first. it scrolls itself, so its parent must give it a height */
export function StreamRows({
  rows,
  selected,
  onSelect,
  empty,
  className,
}: {
  rows: StreamRow[];
  selected?: string;
  onSelect?: (row: StreamDecision) => void;
  empty?: React.ReactNode;
  className?: string;
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState({ start: 0, end: 0 });

  const offsets = useMemo(() => {
    const result = [0];
    for (const row of rows) result.push(result[result.length - 1] + ROW_HEIGHT[row.kind]);
    return result;
  }, [rows]);

  const updateRange = () => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const top = scroller.scrollTop;
    const start = Math.max(0, firstAtOrAfter(offsets, top) - 1 - OVERSCAN);
    const end = Math.min(rows.length, firstAtOrAfter(offsets, top + scroller.clientHeight) + OVERSCAN);
    setRange((current) => (current.start === start && current.end === end ? current : { start, end }));
  };

  const newest = useRef(rows[0]?.key);
  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller && scroller.scrollTop > 0 && newest.current !== rows[0]?.key) {
      const moved = rows.findIndex((row) => row.key === newest.current);
      if (moved > 0) scroller.scrollTop += offsets[moved];
    }
    newest.current = rows[0]?.key;
    updateRange();
  }, [rows, offsets]);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const observer = new ResizeObserver(updateRange);
    observer.observe(scroller);
    return () => observer.disconnect();
  }, [offsets]);

  if (rows.length === 0 && empty) return <>{empty}</>;

  return (
    <div role="table" aria-rowcount={rows.length + 1} className={cn("flex min-h-0 flex-col", className)}>
      <div role="row" aria-rowindex={1} className={cn(COLUMNS, "h-[30px] shrink-0 border-b border-n-line-2")}>
        {["Decided", "Option", "Unit and context", "Why", "Outcome"].map((label) => (
          <span key={label} role="columnheader" className="n-label font-normal text-n-text-3">
            {label}
          </span>
        ))}
      </div>
      <div ref={scrollerRef} role="rowgroup" onScroll={updateRange} className="min-h-0 flex-1 overflow-y-auto">
        <div className="relative" style={{ height: offsets[rows.length] }}>
          {rows.slice(range.start, range.end).map((row, index) => {
            const at = range.start + index;
            return row.kind === "marker" ? (
              <Marker key={row.key} row={row} top={offsets[at]} rowIndex={at + 2} />
            ) : (
              <Decision
                key={row.key}
                row={row}
                top={offsets[at]}
                rowIndex={at + 2}
                selected={row.key === selected}
                onSelect={onSelect}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

const PLACED = "absolute inset-x-0 top-0";

const Decision = memo(function Decision({
  row,
  top,
  rowIndex,
  selected,
  onSelect,
}: {
  row: StreamDecision;
  top: number;
  rowIndex: number;
  selected: boolean;
  onSelect?: (row: StreamDecision) => void;
}) {
  const outcome = OUTCOME[row.outcome.state];
  return (
    <div
      role="row"
      aria-rowindex={rowIndex}
      aria-selected={selected}
      style={{ height: ROW_HEIGHT.decision, transform: `translateY(${top}px)` }}
      className={cn(
        PLACED,
        COLUMNS,
        "border-b border-n-line-2",
        onSelect && "hover:bg-n-fill-1",
        selected && "rounded-n-control bg-n-fill-2 hover:bg-n-fill-2",
      )}
    >
      <span role="cell" className="n-label truncate font-normal tabular-nums text-n-text-3">
        {onSelect && (
          <button type="button" aria-label={`Open the decision for ${row.unit}`} onClick={() => onSelect(row)} className={STRETCHED} />
        )}
        {row.decided}
      </span>
      <span role="cell" className={cn("n-meta truncate", row.option ? "text-n-text-1" : "text-n-text-3")}>
        {row.option ?? "—"}
      </span>
      <span role="cell" className="n-label truncate font-n-mono font-normal text-n-text-3">
        {row.unit}
      </span>
      <span role="cell" className="n-meta truncate text-n-text-2">
        {row.why}
      </span>
      <span role="cell" className="flex min-w-0 items-center gap-2">
        <StateBadge state={outcome.state}>{outcome.label}</StateBadge>
        {row.outcome.note && <span className="n-label truncate font-normal text-n-text-2">{row.outcome.note}</span>}
      </span>
    </div>
  );
});

const Marker = memo(function Marker({ row, top, rowIndex }: { row: StreamMarker; top: number; rowIndex: number }) {
  return (
    <div
      role="row"
      aria-rowindex={rowIndex}
      style={{ height: ROW_HEIGHT.marker, transform: `translateY(${top}px)` }}
      className={cn(PLACED, "flex items-center gap-2 px-2")}
    >
      <span role="cell" className="flex min-w-0 flex-1 items-center gap-2">
        <GitMerge aria-hidden size={12} className="shrink-0 text-n-text-3" />
        {row.href ? (
          <Link href={row.href} className="n-label truncate font-normal text-n-text-2 hover:text-n-text-1">
            {row.label}
          </Link>
        ) : (
          <span className="n-label truncate font-normal text-n-text-2">{row.label}</span>
        )}
        <span aria-hidden className="h-px min-w-6 flex-1 bg-n-line" />
      </span>
    </div>
  );
});
