"use client";

import { useEffect, useState } from "react";
import { notFound } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Play, Rocket } from "lucide-react";
import { Button } from "@qbrix/ui/next/button";
import { Menu } from "@qbrix/ui/next/menu";
import { ObjectPage } from "@qbrix/ui/next/object-page";
import { CouldntLoad } from "@qbrix/ui/next/page-error";
import { usePin } from "@/components/next/shell/pinned";
import { routes } from "@/config/routes";
import { loops } from "@/lib/api/loops";
import { usePageReady } from "@/lib/api/page-ready";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError, type Loop, type ResultsRange } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/context";
import { prompts, statusRow } from "@/lib/header/status";
import { pauseOf } from "@/lib/loop/pause";
import { loopStatus } from "@/lib/loop/status";
import { LoopLoading } from "./loading";
import { LoopOverview } from "./overview";
import { LoopRail } from "./rail";
import { useStagedAction } from "./staged-action";

const RESULTS_POLL_MS = 10_000;
const DETAIL_POLL_MS = 30_000;
const CLOCK_MS = 10_000;

function isMissing(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

function retryUnlessMissing(count: number, error: unknown): boolean {
  return !isMissing(error) && count < 1;
}

function useResults(key: string, range: ResultsRange, enabled: boolean, keepPrevious = false) {
  return useQuery({
    queryKey: queryKeys.loops.results(key, range),
    queryFn: () => loops.results(key, range),
    enabled,
    refetchInterval: RESULTS_POLL_MS,
    staleTime: RESULTS_POLL_MS / 2,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
}

export function LoopPage({ loopKey }: { loopKey: string }) {
  const [range, setRange] = useState<ResultsRange>("cycle");

  const detail = useQuery({
    queryKey: queryKeys.loops.detail(loopKey),
    queryFn: () => loops.get(loopKey),
    refetchInterval: DETAIL_POLL_MS,
    staleTime: DETAIL_POLL_MS / 2,
    retry: retryUnlessMissing,
  });
  const launched = Boolean(detail.data?.cycle);

  const cycle = useResults(loopKey, "cycle", detail.isSuccess);
  const day = useResults(loopKey, "24h", launched);
  const chart = useResults(loopKey, range, launched, true);
  const changes = useQuery({
    queryKey: queryKeys.loops.changes(loopKey),
    queryFn: () => loops.changes(loopKey),
    enabled: detail.isSuccess,
    refetchInterval: DETAIL_POLL_MS,
    staleTime: DETAIL_POLL_MS / 2,
  });

  const ready = usePageReady([detail, cycle, changes]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);

  if (isMissing(detail.error)) notFound();

  const failed = [detail, cycle, changes].find((query) => query.isError && !query.data);
  if (failed) {
    return (
      <CouldntLoad
        requestId={failed.error instanceof ApiError ? failed.error.requestId : undefined}
        onRetry={() => {
          detail.refetch();
          cycle.refetch();
          changes.refetch();
        }}
        home={{ href: routes.next.home, label: "Go to loops" }}
      />
    );
  }

  if (!ready || !detail.data) return <LoopLoading />;

  return (
    <LoopFrame
      loop={detail.data}
      cycleResults={cycle.data}
      dayResults={day.data}
      chartResults={chart.data}
      range={range}
      onRangeChange={setRange}
      changes={changes.data ?? []}
      now={now}
    />
  );
}

function LoopFrame({
  loop,
  cycleResults,
  dayResults,
  chartResults,
  range,
  onRangeChange,
  changes,
  now,
}: Omit<
  React.ComponentProps<typeof LoopOverview>,
  "row" | "status" | "pause" | "staging" | "onCancel" | "onDone"
> & { loop: Loop }) {
  const { user } = useAuth();
  const { staging, actionRef, open, cancel, finish } = useStagedAction(loop.state);
  const canEdit = user?.role !== "viewer";
  const pin = usePin({ kind: "loop", ref: loop.id, name: loop.name, key: loop.key, state: loop.state });
  const status = loopStatus(loop.state, cycleResults);
  const pause = pauseOf(loop, changes);
  const row = statusRow({ kind: "loop", status, alert: pause?.byQbrix });
  const paused = loop.state === "paused";

  return (
    <ObjectPage
      crumbs={[{ label: "Loops", href: routes.next.home }, { label: loop.name }]}
      menu={<Menu items={[pin.menuItem]} />}
      actions={
        staging ? undefined : loop.state === "draft" ? (
          <Button ref={actionRef} size="sm" onClick={open}>
            <Rocket size={13} />
            Launch
          </Button>
        ) : paused ? (
          <Button ref={actionRef} size="sm" onClick={open}>
            <Play size={13} />
            Resume
          </Button>
        ) : undefined
      }
      canEdit={canEdit}
      viewOnly={`Ask ${loop.owner.name} to ${paused ? "resume" : "change"} this loop`}
      rail={
        <LoopRail loop={loop} pause={pause} results={cycleResults} prompts={prompts(row, loop.name)} now={now} />
      }
    >
      <LoopOverview
        loop={loop}
        row={row}
        status={status}
        pause={pause}
        cycleResults={cycleResults}
        dayResults={dayResults}
        chartResults={chartResults}
        range={range}
        onRangeChange={onRangeChange}
        changes={changes}
        now={now}
        staging={staging && canEdit}
        onCancel={cancel}
        onDone={finish}
      />
    </ObjectPage>
  );
}
