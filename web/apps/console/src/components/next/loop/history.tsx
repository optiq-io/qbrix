import { Change, HISTORY_LINE_INSET } from "@qbrix/ui/next/change";
import { RailLine, TimeRail, type RailEntry } from "@qbrix/ui/next/time-rail";
import type { ChangeEntry, LoopCycle } from "@/lib/api/types";
import { toChangeData, toRailEntry } from "@/lib/loop/event";
import { nowLine } from "@/lib/loop/fact";
import type { LoopStatus } from "@/lib/header/status";

export function historyRowId(entryId: string) {
  return `change-${entryId}`;
}

export function RecentHistory({
  changes,
  cycle,
  status,
  selected,
  now,
}: {
  changes: ChangeEntry[];
  cycle: LoopCycle;
  status: LoopStatus;
  selected: string | null;
  now: number;
}) {
  const started = cycle.started_at ? Date.parse(cycle.started_at) : now;
  const entries: RailEntry[] = [
    { key: "now", kind: "now", at: "Now", state: "live" },
    ...changes.map((entry) => toRailEntry(entry, started, now)),
  ];

  return (
    <section className="flex flex-col gap-3">
      <h2 className="n-support font-medium text-n-text-1">History</h2>
      <TimeRail entries={entries}>
        <RailLine entry="now" className="n-meta pb-2 pl-3 text-n-text-3">
          {nowLine(status, cycle, now)}
        </RailLine>
        {changes.map((entry) => (
          <RailLine key={entry.id} entry={entry.id} inset={HISTORY_LINE_INSET} className="n-body">
            <div id={historyRowId(entry.id)}>
              <Change layout="history" change={toChangeData(entry, now)} selected={selected === entry.id} />
            </div>
          </RailLine>
        ))}
      </TimeRail>
    </section>
  );
}
