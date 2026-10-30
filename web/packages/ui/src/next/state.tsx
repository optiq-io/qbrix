import { cn } from "../lib/utils";

/** the only meanings colour has: healthy, needs attention, broken, waits on you */
export type State = "ok" | "part" | "no" | "new";

const DOT: Record<State, string> = {
  ok: "bg-n-ok-fg",
  part: "bg-n-part-fg",
  no: "bg-n-no-fg",
  new: "bg-n-new-fg",
};

const BADGE: Record<State, string> = {
  ok: "bg-n-ok-bg text-n-ok-fg",
  part: "bg-n-part-bg text-n-part-fg",
  no: "bg-n-no-bg text-n-no-fg",
  new: "bg-n-new-bg text-n-new-fg",
};

export function StateDot({ state, className }: { state: State; className?: string }) {
  return <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", DOT[state], className)} />;
}

export function StateBadge({
  state,
  className,
  children,
}: {
  state: State;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span className={cn("n-label inline-flex w-fit shrink-0 items-center rounded-n-chip px-1 py-px", BADGE[state], className)}>
      {children}
    </span>
  );
}
