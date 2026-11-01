"use client";

import { Check, Copy } from "lucide-react";
import { useCopy } from "./copy";
import { RailSection } from "./object-page";

export type WireMetric = { metricKind: "outcome" } | { metricKind: "track"; eventName: string };

export type WireProps = WireMetric & {
  loopKey: string;
  /** a link to the docs page for the reader's SDK */
  docs?: React.ReactNode;
  className?: string;
};

export function wireCalls({ loopKey, ...metric }: { loopKey: string } & WireMetric): [string, string] {
  const select = `select(${JSON.stringify(loopKey)}, ctx)`;
  if (metric.metricKind === "track") return [select, `track(${JSON.stringify(metric.eventName)}, 1)`];
  return [select, "outcome(request_id, 1)"];
}

function Call({ call }: { call: string }) {
  const [copied, copy] = useCopy();
  const Icon = copied ? Check : Copy;

  return (
    <button
      type="button"
      onClick={() => copy(call)}
      aria-label={copied ? "Copied" : `Copy ${call}`}
      className="group flex w-full items-start gap-1 rounded-n-chip text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-n-ink"
    >
      <code className="n-label min-w-0 flex-1 font-n-mono font-normal tracking-normal wrap-anywhere text-n-text-2 group-hover:text-n-text-1">
        {call}
      </code>
      <Icon size={12} className="mt-px shrink-0 text-n-text-3 group-hover:text-n-text-1" />
    </button>
  );
}

export function Wire({ docs, className, ...call }: WireProps) {
  return (
    <RailSection title="Wire it" className={className}>
      <div className="flex flex-col gap-1 rounded-n-panel bg-n-fill-1 px-3 py-2">
        {wireCalls(call).map((line) => (
          <Call key={line} call={line} />
        ))}
      </div>
      {docs}
    </RailSection>
  );
}
