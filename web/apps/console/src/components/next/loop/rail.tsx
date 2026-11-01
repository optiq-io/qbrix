import { AskYourAgent } from "@qbrix/ui/next/empty";
import { MetricRef } from "@qbrix/ui/next/entity";
import { Health } from "@qbrix/ui/next/health";
import { Property, RailSection } from "@qbrix/ui/next/object-page";
import type { State } from "@qbrix/ui/next/state";
import { Wire } from "@qbrix/ui/next/wire";
import type { Loop, LoopResults } from "@/lib/api/types";
import { healthSignals, windowLabel } from "@/lib/loop/fact";

const STATE: Record<Loop["state"], { label: string; state?: State }> = {
  draft: { label: "Draft" },
  live: { label: "Live", state: "ok" },
  paused: { label: "Paused", state: "part" },
};

function engine(loop: Loop): string {
  const [id] = loop.engine.split(":");
  const name = id.charAt(0).toUpperCase() + id.slice(1);
  return loop.cycle ? `${name} ${loop.cycle.engine_version}` : name;
}

export function LoopRail({
  loop,
  results,
  prompts,
  now,
}: {
  loop: Loop;
  results: LoopResults | undefined;
  prompts: string[];
  now: number;
}) {
  const fallback = loop.options.find((option) => option.key === loop.fallback)?.name ?? loop.fallback;
  const signals = healthSignals(results, now);

  return (
    <>
      <RailSection title="Loop">
        <Property label="State" value={STATE[loop.state].label} state={STATE[loop.state].state} />
        {loop.cycle && <Property label="Cycle" value={`${loop.cycle.number} of ${loop.cycle.number}`} />}
        <Property label="Engine" value={engine(loop)} />
        <Property label="Metric" value={<MetricRef name={loop.metric.name} />} />
        <Property label="Window" value={windowLabel(loop.metric.window_seconds)} />
      </RailSection>
      <RailSection title="Delivery">
        <Property label="Audience" value="Everyone" />
        <Property label="Rollout" value="100%" />
        <Property label="Fallback" value={fallback} />
      </RailSection>
      {signals.length > 0 && <Health signals={signals} />}
      <Wire loopKey={loop.key} metricKind="outcome" />
      <AskYourAgent label="Ask your agent · about what's happening" prompts={prompts} className="mt-auto" />
    </>
  );
}
