"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Picker } from "@qbrix/ui/next/picker";
import { CreateMetricDialog } from "@/components/next/metric/create-metric-dialog";
import { metrics } from "@/lib/api/metrics";
import { queryKeys } from "@/lib/api/query-keys";
import { windowLabel } from "@/lib/loop/fact";
import { metricTypeLabel, usedBy } from "@/lib/metric/new-metric";
import { Fact, Section } from "./section";

export function MetricSection({
  value,
  error,
  onChange,
}: {
  value: string | null;
  error: string | undefined;
  onChange: (name: string) => void;
}) {
  const [creating, setCreating] = useState(false);
  const listed = useQuery({ queryKey: queryKeys.metrics.list, queryFn: metrics.list });
  const picked = listed.data?.find((metric) => metric.name === value);

  return (
    <>
      <Section title="Metric" note="pick a metric, or create one">
        <Picker
          hideLabel
          label="Metric"
          className="max-w-[360px]"
          placeholder={listed.isPending ? "Loading metrics…" : "Choose a metric"}
          value={value}
          error={error ?? (listed.isError ? "Couldn't load your metrics." : undefined)}
          options={(listed.data ?? []).map((metric) => ({
            value: metric.name,
            label: metric.name,
            hint: `${metricTypeLabel(metric.type)} · ${windowLabel(metric.window_seconds)}`,
          }))}
          onChange={onChange}
          create={{ label: "Create metric", onSelect: () => setCreating(true) }}
        />
        {picked && (
          <>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
              <Fact label="Type" value={metricTypeLabel(picked.type)} />
              <Fact label="Window" value={windowLabel(picked.window_seconds)} />
              <Fact label="Used by" value={usedBy(picked)} quiet={picked.loops.length === 0} />
            </div>
            <p className="n-body text-n-text-2">{picked.semantic}</p>
          </>
        )}
      </Section>

      <Section title="Engine and context" note="engines have no settings">
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <Fact label="Engine" value="Spinoza" />
          {picked && <Fact label="Chosen from" value={`${picked.type}, the metric's type`} />}
          <Fact label="Context" value="none" quiet />
        </div>
      </Section>

      <CreateMetricDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(metric) => onChange(metric.name)}
      />
    </>
  );
}
