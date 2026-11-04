"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@qbrix/ui/next/button";
import { AskYourAgent, Code } from "@qbrix/ui/next/empty";
import { List } from "@qbrix/ui/next/list";
import { ObjectPage, RailSection } from "@qbrix/ui/next/object-page";
import { useFrozen } from "@qbrix/ui/next/offline";
import { CouldntLoad } from "@qbrix/ui/next/page-error";
import { Header } from "@/components/next/header/header";
import { routes } from "@/config/routes";
import { metrics as metricsApi } from "@/lib/api/metrics";
import { usePageReady } from "@/lib/api/page-ready";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError, type Metric } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/context";
import { facts } from "@/lib/header/fact";
import { eyebrow, prompts, statusRow } from "@/lib/header/status";
import { metricsCounters } from "@/lib/metric/list";
import { MetricsLoading } from "./loading";
import { MetricFields, useMetricForm } from "./metric-form";
import { METRIC_COLUMNS } from "./metric-row";

const LIST_POLL_MS = 10_000;
const CLOCK_MS = 10_000;

export function MetricsPage() {
  const list = useQuery({
    queryKey: queryKeys.metrics.list,
    queryFn: metricsApi.list,
    refetchInterval: LIST_POLL_MS,
    staleTime: LIST_POLL_MS / 2,
  });
  const ready = usePageReady([list]);

  if (list.isError && !list.data) {
    return (
      <CouldntLoad
        requestId={list.error instanceof ApiError ? list.error.requestId : undefined}
        onRetry={() => list.refetch()}
        home={{ href: routes.next.home, label: "Go to loops" }}
      />
    );
  }

  if (!ready || !list.data) return <MetricsLoading />;

  return <MetricsFrame metrics={list.data} updatedAt={list.dataUpdatedAt} />;
}

function MetricsFrame({ metrics, updatedAt }: { metrics: Metric[]; updatedAt: number }) {
  const { user } = useAuth();
  const frozen = useFrozen();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);

  const viewer = user?.role === "viewer";
  const canEdit = !viewer && !frozen;
  const row = statusRow({ kind: "metrics", count: metrics.length, alerts: 0 });
  const none = metrics.length === 0;

  return (
    <ObjectPage
      crumbs={[{ label: "Metrics" }]}
      canEdit={canEdit}
      viewOnly={viewer ? "Ask an admin or a member to add metrics" : undefined}
      rail={
        <>
          <AskYourAgent prompts={prompts(row, "")} />
          {canEdit && <NewMetric />}
        </>
      }
    >
      <div className="flex flex-col gap-10">
        <Header
          row={row}
          eyebrow={eyebrow(row, metricsCounters(metrics, updatedAt, now))}
          facts={facts(row, {})}
        />
        {none ? (
          <HowItArrives />
        ) : (
          <div className="flex flex-col gap-3">
            <List items={metrics} rowKey={(metric) => metric.id} columns={METRIC_COLUMNS} rowLabel={(metric) => metric.name} />
            <p className="n-meta text-n-text-3">A metric can serve several loops; one event then counts for each of them.</p>
          </div>
        )}
      </div>
    </ObjectPage>
  );
}

function NewMetric() {
  const form = useMetricForm(() => {});
  return (
    <RailSection title="New metric">
      <MetricFields form={form} />
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={form.pending} onClick={form.submit}>
          {form.pending ? "Creating" : "Create metric"}
        </Button>
        <Button size="sm" variant="quiet" disabled={form.pending} onClick={form.reset}>
          Cancel
        </Button>
      </div>
    </RailSection>
  );
}

function HowItArrives() {
  return (
    <section className="flex max-w-[620px] flex-col gap-3">
      <h2 className="n-meta font-medium text-n-text-3">How it arrives</h2>
      <p className="n-body text-n-text-2">
        Once it exists, your code sends it with track, and qbrix credits the decisions that led to it:
      </p>
      <Code>track(&quot;checkout_completed&quot;, 1)</Code>
    </section>
  );
}
