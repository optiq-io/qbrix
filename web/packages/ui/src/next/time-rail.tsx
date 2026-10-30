"use client";

import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "../lib/utils";

export type RailEntry = {
  key: string;
  kind: "now" | "cycle" | "began" | "tick" | "declined" | "pause" | "origin";
  /** already formatted: "12 Oct", "Cycle 2", "Now". a date repeated within a cycle shows once */
  at?: string;
  cycle?: number;
  state: "live" | "sealed";
};

const HOLLOW = "border-[1.5px] bg-n-surface";

const MARK: Record<RailEntry["kind"], Record<RailEntry["state"], string>> = {
  now: {
    live: "size-[9px] bg-n-ok-fg shadow-[0_0_6px_var(--n-ok-fg)]",
    sealed: cn("size-[9px] border-n-text-3", HOLLOW),
  },
  cycle: {
    live: "size-[13px] border-[1.5px] border-n-surface bg-n-text-1",
    sealed: cn("size-[13px] border-n-viz-2", HOLLOW),
  },
  began: {
    live: cn("size-[9px] border-n-text-1", HOLLOW),
    sealed: cn("size-[9px] border-n-viz-2", HOLLOW),
  },
  tick: { live: "size-1.5 bg-n-text-1", sealed: "size-1.5 bg-n-viz-2" },
  declined: {
    live: cn("size-[7px] border-n-text-1", HOLLOW),
    sealed: cn("size-[7px] border-n-viz-2", HOLLOW),
  },
  pause: { live: "size-[7px] bg-n-part-fg", sealed: "size-[7px] bg-n-part-fg" },
  origin: {
    live: cn("size-[9px] border-n-viz-2", HOLLOW),
    sealed: cn("size-[9px] border-n-viz-2", HOLLOW),
  },
};

function dateTone({ kind, state }: RailEntry) {
  if (kind === "now" || kind === "began") return "text-n-text-1";
  if (kind === "cycle") return state === "live" ? "text-n-text-1" : "text-n-text-2";
  return "font-normal text-n-text-3";
}

const RailEntries = createContext<RailEntry[]>([]);

function samePositions(a: Record<string, number>, b: Record<string, number>) {
  const keys = Object.keys(b);
  return keys.length === Object.keys(a).length && keys.every((key) => Math.abs(a[key] - b[key]) < 0.25);
}

export function TimeRail({
  entries,
  className,
  children,
}: {
  /** newest first, the order the lines read in */
  entries: RailEntry[];
  className?: string;
  children: React.ReactNode;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [positions, setPositions] = useState<Record<string, number>>({});

  const measure = () => {
    const root = rootRef.current;
    if (!root) return;
    const top = root.getBoundingClientRect().top;
    const next: Record<string, number> = {};
    root.querySelectorAll<HTMLElement>("[data-rail-probe]").forEach((probe) => {
      const rect = probe.getBoundingClientRect();
      next[probe.dataset.railProbe as string] = rect.top + rect.height / 2 - top;
    });
    setPositions((current) => (samePositions(current, next) ? current : next));
  };

  useLayoutEffect(measure);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    root.querySelectorAll("[data-rail-line]").forEach((line) => observer.observe(line));
    return () => observer.disconnect();
  }, [entries]);

  const placed = entries.filter((entry) => positions[entry.key] !== undefined);
  const first = placed[0] && positions[placed[0].key];
  const last = placed.length > 0 ? positions[placed[placed.length - 1].key] : undefined;
  const lastLive = placed.filter((entry) => entry.state === "live").pop();
  const liveEnd = lastLive ? positions[lastLive.key] : first;

  return (
    <RailEntries.Provider value={entries}>
      <div ref={rootRef} className={cn("flex", className)}>
        <div aria-hidden className="relative w-[72px] shrink-0">
          {first !== undefined && last !== undefined && liveEnd !== undefined && (
            <>
              <span className="absolute left-[63.25px] w-[1.5px] bg-n-text-1" style={{ top: first, height: liveEnd - first }} />
              <span className="absolute left-[63.25px] w-[1.5px] bg-n-viz-2" style={{ top: liveEnd, height: last - liveEnd }} />
            </>
          )}
          {placed.map((entry, index) => {
            const previous = placed[index - 1];
            const repeated = previous?.at === entry.at && previous?.cycle === entry.cycle;
            return (
              <div key={entry.key} className="absolute left-0 w-full" style={{ top: positions[entry.key] }}>
                {entry.at && !repeated && (
                  <span className={cn("n-label absolute right-5 -translate-y-1/2 whitespace-nowrap", dateTone(entry))}>
                    {entry.at}
                  </span>
                )}
                <span
                  className={cn(
                    "absolute left-16 -translate-x-1/2 -translate-y-1/2 rounded-full",
                    MARK[entry.kind][entry.state],
                  )}
                />
              </div>
            );
          })}
        </div>
        <div className="min-w-0 flex-1 pl-2">{children}</div>
      </div>
    </RailEntries.Provider>
  );
}

/** the line a rail entry aligns with, anywhere inside the rail: its mark sits on this element's first line.
    set the line's type here, since the first line's height is read from it */
export function RailLine({
  entry,
  inset = 0,
  className,
  children,
}: {
  entry: string;
  /** how far below this element its first line starts, for content with its own padding */
  inset?: number;
  className?: string;
  children?: React.ReactNode;
}) {
  const at = useContext(RailEntries).find((candidate) => candidate.key === entry)?.at;

  return (
    <div data-rail-line className={cn("relative", className)}>
      <span
        aria-hidden
        data-rail-probe={entry}
        className="pointer-events-none absolute left-0 w-0"
        style={{ top: inset, height: "1lh" }}
      />
      {at && <span className="sr-only">{at}</span>}
      {children}
    </div>
  );
}
