"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "../lib/utils";
import { frozenAt, useFrozen } from "./offline";

const FROM_SHOWN_MS = 5000;
const FROM_FADE_MS = 600;

export type LiveNumberMode = "tick" | "step" | "frozen" | "early";

/** each number moves at the pace its data changes: rates tick, shares and lift
    step when qbrix learns, young lift says it is early, and a frozen figure says
    since when. while the server isn't answering, every mode stands still */
export function LiveNumber({
  mode,
  value,
  since,
  showFrom = true,
  className,
}: {
  mode: LiveNumberMode;
  /** already formatted: "58%", "38", "+0.8%" */
  value: string;
  /** when a paused loop froze. without it, frozen reads when the server stopped answering */
  since?: Date;
  /** off where there's no room beside the number */
  showFrom?: boolean;
  className?: string;
}) {
  const unreachable = useFrozen();
  const frozen = mode === "frozen" || unreachable !== null;
  const steps = (mode === "step" || mode === "early") && !frozen;
  const frozenSince = since ?? unreachable;

  const [roll, setRoll] = useState(0);
  const [from, setFrom] = useState<{ value: string; shown: boolean } | null>(null);
  const last = useRef(value);

  useEffect(() => {
    const previous = last.current;
    last.current = value;
    if (!steps) {
      setFrom(null);
      return;
    }
    if (previous === value) return;

    setRoll((count) => count + 1);
    setFrom({ value: previous, shown: true });
    const hide = setTimeout(() => setFrom({ value: previous, shown: false }), FROM_SHOWN_MS);
    const clear = setTimeout(() => setFrom(null), FROM_SHOWN_MS + FROM_FADE_MS);
    return () => {
      clearTimeout(hide);
      clearTimeout(clear);
    };
  }, [value, steps]);

  return (
    <span className={cn("inline-flex items-baseline gap-1.5 tabular-nums", className, frozen && "text-n-text-3")}>
      <span className="inline-flex overflow-hidden">
        <span key={roll} className={cn("inline-block", steps && roll > 0 && "n-number-step")}>
          {value}
        </span>
      </span>
      {mode === "early" && <span>· early</span>}
      {mode === "frozen" && frozenSince && (
        <span className="n-meta whitespace-nowrap font-normal text-n-text-3">since {frozenAt(frozenSince)}</span>
      )}
      {showFrom && from && (
        <span
          className={cn(
            "n-meta whitespace-nowrap font-normal text-n-text-3 transition-opacity duration-[600ms] motion-reduce:transition-none",
            !from.shown && "opacity-0",
          )}
        >
          from {from.value} · just learned
        </span>
      )}
    </span>
  );
}

const PULSE = {
  live: "n-pulse-beat bg-n-ok-fg",
  paused: "bg-n-part-fg",
  idle: "bg-n-text-3",
  empty: "border-[1.5px] border-n-text-3",
};

/** the once-a-second beat on the live line. only live beats; nothing yet is hollow, as
    is anything while the server isn't answering */
export function LivePulse({ tone = "live", className }: { tone?: keyof typeof PULSE; className?: string }) {
  const unreachable = useFrozen();
  return (
    <span aria-hidden className={cn("inline-block size-[7px] shrink-0 rounded-full", PULSE[unreachable ? "empty" : tone], className)} />
  );
}
