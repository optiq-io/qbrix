import { cn } from "../lib/utils";

export type ExperimentState =
  | "cold-start"
  | "learning"
  | "exploring"
  | "converged"
  | "degraded"
  | "enabled"
  | "paused";

type StateConfig = {
  label: string;
  fillClass: string;
  strokeClass: string;
  textClass: string;
  dotClass: string;
};

// one alpha pair for every state — /10 ground, /20 hairline. two states used
// /10+/25 and the rest /[0.08]+/20, which read as a difference nobody chose.
// every class is spelled out: tailwind scans source for literal strings, so a
// composed `bg-${tone}/10` would never be emitted.
//
// the design board recolours only the dot and label per state and leaves every
// badge on the accent ground; that is a board bug, not a spec — a paused badge
// on a lime ground is wrong. the per-state tint here is kept deliberately.
const states: Record<ExperimentState, StateConfig> = {
  "cold-start": {
    label: "cold start",
    fillClass: "bg-text-secondary/10",
    strokeClass: "border-text-secondary/20",
    textClass: "text-text-secondary",
    dotClass: "bg-text-secondary",
  },
  learning: {
    label: "learning",
    fillClass: "bg-info/10",
    strokeClass: "border-info/20",
    textClass: "text-info",
    dotClass: "bg-info",
  },
  exploring: {
    label: "exploring",
    fillClass: "bg-info/10",
    strokeClass: "border-info/20",
    textClass: "text-info",
    dotClass: "bg-info",
  },
  converged: {
    label: "converged",
    fillClass: "bg-accent/10",
    strokeClass: "border-accent/20",
    textClass: "text-accent",
    dotClass: "bg-accent",
  },
  degraded: {
    label: "degraded",
    fillClass: "bg-danger/10",
    strokeClass: "border-danger/20",
    textClass: "text-danger",
    dotClass: "bg-danger",
  },
  // was the legacy `teal` alias; viz-3 is the same hue as a real v3 token
  enabled: {
    label: "enabled",
    fillClass: "bg-viz-3/10",
    strokeClass: "border-viz-3/20",
    textClass: "text-viz-3",
    dotClass: "bg-viz-3",
  },
  paused: {
    label: "paused",
    fillClass: "bg-amber/10",
    strokeClass: "border-amber/20",
    textClass: "text-amber",
    dotClass: "bg-amber",
  },
};

type StateBadgeProps = {
  state: ExperimentState;
  label?: string;
  className?: string;
};

export function StateBadge({ state, label, className }: StateBadgeProps) {
  const cfg = states[state];
  return (
    <span
      className={cn(
        // fixed min-width + justify-center keeps enabled / paused / etc. visually
        // uniform regardless of label length, and centers the dot+text pair.
        "inline-flex h-[22px] min-w-[82px] items-center justify-center gap-1.5 rounded border px-2.5",
        cfg.fillClass,
        cfg.strokeClass,
        className,
      )}
    >
      <span className={cn("h-[5px] w-[5px] shrink-0 rounded-full", cfg.dotClass)} />
      <span
        className={cn(
          "font-mono text-[10.5px] font-semibold uppercase leading-none tracking-[0.04em]",
          cfg.textClass,
        )}
      >
        {label ?? cfg.label}
      </span>
    </span>
  );
}
