import type { Loop, LoopResults } from "@/lib/api/types";
import type { LoopStatus } from "@/lib/header/status";

/** a live loop warms up until its cycle's first window has closed with a sealed decision.
    a sealed decision alone isn't enough: a conversion seals the moment its outcome arrives */
export function loopStatus(state: Loop["state"], cycle: LoopResults | undefined): LoopStatus {
  if (state !== "live") return state;
  const windowClosed = Boolean(cycle?.lift);
  const sealed = cycle?.share?.options.some((option) => option.sealed > 0) ?? false;
  return windowClosed && sealed ? "live" : "warming_up";
}
