"use client";

import { useCallback, useMemo, useState } from "react";
import { ShareChart } from "@qbrix/ui/next/share-chart";
import { Header } from "@/components/next/header/header";
import type { ChangeEntry, Loop, LoopResults, ResultsRange } from "@/lib/api/types";
import { facts } from "@/lib/header/fact";
import { eyebrow, type StatusRow, type LoopStatus } from "@/lib/header/status";
import { toHeaderEvent, toPin } from "@/lib/loop/event";
import { chartCaption, loopCounters, loopFacts } from "@/lib/loop/fact";
import { DraftOverview } from "./draft-overview";
import { historyRowId, RecentHistory } from "./history";

const RECENT = 5;

export function LoopOverview({
  loop,
  row,
  status,
  cycleResults,
  dayResults,
  chartResults,
  range,
  onRangeChange,
  changes,
  now,
  staging,
  onStagingEnd,
}: {
  loop: Loop;
  row: StatusRow;
  status: LoopStatus;
  cycleResults: LoopResults | undefined;
  dayResults: LoopResults | undefined;
  chartResults: LoopResults | undefined;
  range: ResultsRange;
  onRangeChange: (range: ResultsRange) => void;
  changes: ChangeEntry[];
  now: number;
  staging: boolean;
  onStagingEnd: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const events = useMemo(() => changes.map(toHeaderEvent), [changes]);
  const started = loop.cycle?.started_at ? Date.parse(loop.cycle.started_at) : null;
  const pins = useMemo(
    () => changes.filter((entry) => started !== null && entry.at && Date.parse(entry.at) >= started).map(toPin),
    [changes, started],
  );
  const onPin = useCallback((entryId: string) => {
    setSelected(entryId);
    document.getElementById(historyRowId(entryId))?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  const share = chartResults?.share;

  return (
    <div className="flex flex-col gap-8">
      <Header
        name={loop.name}
        row={row}
        eyebrow={eyebrow(row, cycleResults ? loopCounters(cycleResults, now) : {})}
        events={events}
        facts={facts(row, loopFacts(status, loop, { cycle: cycleResults, day: dayResults }, now))}
      />
      {loop.state === "draft" && (
        <DraftOverview loop={loop} results={cycleResults} staging={staging} onStagingEnd={onStagingEnd} />
      )}
      {share && chartResults && (
        <ShareChart
          since={Date.parse(share.since)}
          until={Date.parse(share.until)}
          options={share.options.map(({ key, name }) => ({ key, name }))}
          columns={share.series.map((point) => ({ at: Date.parse(point.at), decisions: point.decisions }))}
          pins={pins}
          onPin={onPin}
          range={range}
          onRangeChange={onRangeChange}
          caption={chartCaption(chartResults, range, status === "warming_up")}
        />
      )}
      {loop.cycle && loop.state === "live" && (
        <RecentHistory
          changes={changes.slice(0, RECENT)}
          cycle={loop.cycle}
          status={status}
          selected={selected}
          now={now}
        />
      )}
    </div>
  );
}
