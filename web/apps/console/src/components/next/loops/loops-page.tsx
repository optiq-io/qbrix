"use client";

import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Button } from "@qbrix/ui/next/button";
import { AskYourAgent } from "@qbrix/ui/next/empty";
import { List } from "@qbrix/ui/next/list";
import { ObjectPage } from "@qbrix/ui/next/object-page";
import { useFrozen } from "@qbrix/ui/next/offline";
import { CouldntLoad } from "@qbrix/ui/next/page-error";
import { Header } from "@/components/next/header/header";
import { routes } from "@/config/routes";
import { loops as loopsApi } from "@/lib/api/loops";
import { usePageReady } from "@/lib/api/page-ready";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError, type LoopListItem } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/context";
import { facts } from "@/lib/header/fact";
import { eyebrow, prompts, statusRow } from "@/lib/header/status";
import {
  alertCount,
  orderLoops,
  pausesByLoop,
  searchLoops,
  workspaceCounters,
  workspaceCounts,
  workspaceEvents,
  workspaceFacts,
} from "@/lib/loop/list";
import { LoopsLoading } from "./loading";
import { loopColumns } from "./loop-row";
import { NewLoopLink, NoLoops } from "./no-loops";

const LIST_POLL_MS = 10_000;
const CHANGES_POLL_MS = 30_000;
const CLOCK_MS = 10_000;

export function LoopsPage() {
  const list = useInfiniteQuery({
    queryKey: queryKeys.loops.list,
    queryFn: ({ pageParam }) => loopsApi.list(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: LIST_POLL_MS,
    staleTime: LIST_POLL_MS / 2,
  });
  const changes = useQuery({
    queryKey: queryKeys.loops.workspaceChanges,
    queryFn: loopsApi.workspaceChanges,
    refetchInterval: CHANGES_POLL_MS,
    staleTime: CHANGES_POLL_MS / 2,
  });
  const pauseEntries = useQuery({
    queryKey: queryKeys.loops.pauses,
    queryFn: loopsApi.pauses,
    refetchInterval: CHANGES_POLL_MS,
    staleTime: CHANGES_POLL_MS / 2,
  });

  const ready = usePageReady([list, changes, pauseEntries]);
  const loaded = useMemo(() => list.data?.pages.flatMap((page) => page.loops) ?? [], [list.data]);

  const failed = [list, changes, pauseEntries].find((query) => query.isError && !query.data);
  if (failed) {
    return (
      <CouldntLoad
        requestId={failed.error instanceof ApiError ? failed.error.requestId : undefined}
        onRetry={() => {
          list.refetch();
          changes.refetch();
          pauseEntries.refetch();
        }}
        home={{ href: routes.next.inbox, label: "Go to inbox" }}
      />
    );
  }

  if (!ready) return <LoopsLoading />;

  return (
    <LoopsFrame
      loaded={loaded}
      more={list.hasNextPage}
      loadingMore={list.isFetchingNextPage}
      onLoadMore={() => list.fetchNextPage()}
      recent={changes.data ?? []}
      pauseEntries={pauseEntries.data ?? []}
    />
  );
}

function LoopsFrame({
  loaded,
  more,
  loadingMore,
  onLoadMore,
  recent,
  pauseEntries,
}: {
  loaded: LoopListItem[];
  more: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  recent: Parameters<typeof workspaceEvents>[0];
  pauseEntries: Parameters<typeof workspaceEvents>[1];
}) {
  const { user } = useAuth();
  const frozen = useFrozen();
  const [query, setQuery] = useState("");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);

  const viewer = user?.role === "viewer";
  const canEdit = !viewer && !frozen;

  const pauses = useMemo(() => pausesByLoop(loaded, pauseEntries), [loaded, pauseEntries]);
  const counts = useMemo(() => workspaceCounts(loaded), [loaded]);
  const events = useMemo(() => workspaceEvents(recent, pauseEntries, pauses), [recent, pauseEntries, pauses]);
  const shown = useMemo(() => searchLoops(orderLoops(loaded), query), [loaded, query]);
  const columns = useMemo(() => loopColumns(pauses, now), [pauses, now]);

  const row = statusRow({
    kind: "workspace",
    loops: loaded.length,
    live: counts.learning + counts.warmingUp,
    alerts: alertCount(pauses),
    asks: 0,
  });
  const none = loaded.length === 0;

  return (
    <ObjectPage
      crumbs={[{ label: "Loops" }]}
      actions={<NewLoopLink />}
      canEdit={canEdit}
      viewOnly={viewer ? "Ask an admin or a member to change loops" : undefined}
      rail={
        <AskYourAgent
          label={none ? "Ask your agent · to get started" : "Ask your agent · about what's happening"}
          prompts={prompts(row, "")}
          className="mt-auto"
        />
      }
    >
      <div className="flex flex-col gap-10">
        <Header
          row={row}
          eyebrow={eyebrow(row, workspaceCounters(loaded, more))}
          events={events}
          facts={facts(row, workspaceFacts(counts))}
        />
        {none ? (
          <NoLoops canEdit={canEdit} />
        ) : (
          <div className="flex flex-col gap-4">
            <List
              items={shown}
              rowKey={(loop) => loop.id}
              columns={columns}
              rowLabel={(loop) => loop.name}
              href={(loop) => routes.next.loop(loop.key)}
              controls={
                <label className="relative block w-64 max-w-full">
                  <Search
                    size={13}
                    aria-hidden
                    className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-n-text-3"
                  />
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search by name or key"
                    aria-label="Search loops by name or key"
                    className="n-meta h-7 w-full rounded-n-control border border-n-line bg-transparent pl-7 pr-2 text-n-text-1 placeholder:text-n-text-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-n-ink"
                  />
                </label>
              }
              empty={<p className="n-body text-n-text-2">No loaded loop matches &ldquo;{query.trim()}&rdquo;.</p>}
            />
            {more && (
              <div>
                <Button variant="secondary" size="sm" disabled={loadingMore} onClick={onLoadMore}>
                  Load more
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </ObjectPage>
  );
}
