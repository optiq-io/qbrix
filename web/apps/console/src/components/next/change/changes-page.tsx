"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { AskYourAgent } from "@qbrix/ui/next/empty";
import { ObjectPage } from "@qbrix/ui/next/object-page";
import { useFrozen } from "@qbrix/ui/next/offline";
import { CouldntLoad } from "@qbrix/ui/next/page-error";
import { Header } from "@/components/next/header/header";
import { routes } from "@/config/routes";
import { changes } from "@/lib/api/changes";
import { loops as loopsApi } from "@/lib/api/loops";
import { usePageReady } from "@/lib/api/page-ready";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError, type ChangeCounts, type ChangeEntry } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/context";
import { changesEyebrow } from "@/lib/change/eyebrow";
import { filterParams, hasFilters, parseFilters, type ChangeFilters } from "@/lib/change/filter";
import { canUndo } from "@/lib/change/row";
import { ChangePanel } from "./change-panel";
import { ChangesList } from "./changes-list";
import { useChangeRows, type ChangeRow } from "./fold";
import { ChangesLoading, PANEL_RAIL } from "./loading";
import { useChangeKeys } from "./use-keyboard";
import { useUndo } from "./use-undo";

const POLL_MS = 30_000;
const CLOCK_MS = 60_000;

/** which row an address means: a change on its own row before a fold that starts with it */
function rowFor(rows: ChangeRow[], id: string): ChangeRow | undefined {
  return rows.find((row) => row.entry.id === id && row.entry.count === 1) ?? rows.find((row) => row.entry.id === id);
}

export function ChangesPage() {
  const params = useSearchParams();
  const pathname = usePathname();
  const filters = useMemo(() => parseFilters(params), [params]);
  const addressed = params.get("change");

  const list = useInfiniteQuery({
    queryKey: queryKeys.changes.list(filters),
    queryFn: ({ pageParam }) => changes.list(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    // a poll refetches every page, so only the first screen stays live
    refetchInterval: (query) => ((query.state.data?.pages.length ?? 0) > 1 ? false : POLL_MS),
  });
  const counts = useQuery({
    queryKey: queryKeys.changes.counts(filters),
    queryFn: () => changes.counts(filters),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_MS,
  });
  const loopList = useInfiniteQuery({
    queryKey: queryKeys.loops.list,
    queryFn: ({ pageParam }) => loopsApi.list(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const ready = usePageReady([list, counts]);
  const entries = useMemo(() => list.data?.pages.flatMap((page) => page.changes) ?? [], [list.data]);
  const loops = useMemo(() => loopList.data?.pages.flatMap((page) => page.loops) ?? [], [loopList.data]);

  // a filter the workspace no longer has, such as a deleted loop's key, finds nothing
  const staleFilter = list.error instanceof ApiError && list.error.status === 404;

  if (list.isError && !list.data && !staleFilter) {
    return (
      <CouldntLoad
        requestId={list.error instanceof ApiError ? list.error.requestId : undefined}
        onRetry={() => list.refetch()}
        home={{ href: routes.next.home, label: "Go to loops" }}
      />
    );
  }
  if (!ready) return <ChangesLoading />;

  return (
    <ChangesFrame
      entries={entries}
      filters={filters}
      counts={counts.data}
      loops={loops}
      addressed={addressed}
      pathname={pathname}
      settled={!list.isPlaceholderData}
      more={list.hasNextPage}
      loadingMore={list.isFetchingNextPage}
      onLoadMore={list.fetchNextPage}
    />
  );
}

function ChangesFrame({
  entries,
  filters,
  counts,
  loops,
  addressed,
  pathname,
  settled,
  more,
  loadingMore,
  onLoadMore,
}: {
  entries: ChangeEntry[];
  filters: ChangeFilters;
  counts: ChangeCounts | undefined;
  loops: { key: string; name: string }[];
  addressed: string | null;
  pathname: string;
  settled: boolean;
  more: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}) {
  const { user } = useAuth();
  const frozen = useFrozen();
  const viewer = user?.role === "viewer";
  const canEdit = !viewer && !frozen;

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);

  const [picked, setPicked] = useState<string | null>(null);
  const [opened, setOpened] = useState<Set<string>>(() => new Set());
  const [reason, setReason] = useState("");

  const pickedId = picked?.split("/").pop() ?? null;
  // an address inside a fold opens it, unless the person chose the fold's own row
  const open = useMemo(() => {
    if (!addressed || pickedId === addressed) return opened;
    const fold = entries.find((entry) => entry.count > 1 && entry.ids.includes(addressed));
    return fold ? new Set(opened).add(fold.id) : opened;
  }, [addressed, entries, opened, pickedId]);

  const rows = useChangeRows(entries, open);

  const pickedRow = rows.find((row) => row.key === picked);
  const selectedRow = addressed
    ? pickedRow?.entry.id === addressed
      ? pickedRow
      : rowFor(rows, addressed)
    : (pickedRow ?? rows[0]);
  const selectedKey = selectedRow?.key ?? null;

  // holds the selection on its row when a newer change arrives above it
  useEffect(() => {
    if (!addressed && settled && !pickedRow && rows[0]) setPicked(rows[0].key);
  }, [addressed, settled, pickedRow, rows]);

  useEffect(() => setReason(""), [selectedKey, addressed]);

  const address = useCallback(
    (nextFilters: ChangeFilters, change: string | null) => {
      const next = filterParams(nextFilters);
      if (change) next.set("change", change);
      return next.size > 0 ? `${pathname}?${next}` : pathname;
    },
    [pathname],
  );

  const onFilters = (next: ChangeFilters) => {
    setPicked(null);
    window.history.pushState(null, "", address(next, null));
  };
  const select = (key: string) => {
    const row = rows.find((candidate) => candidate.key === key);
    if (!row) return;
    setPicked(key);
    window.history.replaceState(null, "", address(filters, row.entry.id));
  };
  const openChange = (id: string) => {
    setPicked(null);
    window.history.replaceState(null, "", address(filters, id));
  };
  const toggleFold = (id: string) => {
    const collapsing = open.has(id);
    setOpened((current) => {
      const next = new Set(current);
      if (collapsing) next.delete(id);
      else next.add(id);
      return next;
    });
    if (collapsing && selectedRow?.foldKey === id) select(id);
  };

  const { undo, pending, refusalFor } = useUndo({ onUndone: () => setReason("") });

  const undoRow = (row: ChangeRow) => {
    if (row.key !== selectedKey) select(row.key);
    undo(row.entry.id, row.key === selectedKey ? reason.trim() || undefined : undefined);
  };

  const keys = useMemo(() => rows.map((row) => row.key), [rows]);
  useChangeKeys({
    keys,
    selected: selectedKey,
    onSelect: select,
    onUndo: () => {
      if (canEdit && selectedRow && canUndo(selectedRow.entry)) undoRow(selectedRow);
    },
  });

  const direct = useQuery({
    queryKey: queryKeys.changes.detail(addressed ?? ""),
    queryFn: () => changes.get(addressed ?? ""),
    enabled: Boolean(addressed) && !selectedRow,
  });
  const entry = selectedRow?.entry ?? direct.data;

  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = sentinel.current;
    if (!element || !more || loadingMore) return;
    const observer = new IntersectionObserver(
      ([seen]) => {
        if (seen.isIntersecting) onLoadMore();
      },
      { rootMargin: "400px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [more, loadingMore, onLoadMore, entries.length]);

  const none = entries.length === 0 && !hasFilters(filters);

  return (
    <ObjectPage
      crumbs={[{ label: "Changes" }]}
      canEdit={canEdit}
      viewOnly={viewer ? "Ask an admin or a member to undo a change" : undefined}
      railClassName={PANEL_RAIL}
      rail={
        entry ? (
          <ChangePanel
            entry={entry}
            canEdit={canEdit}
            refusal={refusalFor(entry.id)}
            reason={reason}
            pending={pending}
            foldOpen={open.has(entry.id)}
            now={now}
            onReason={setReason}
            onUndo={() => undo(entry.id, reason.trim() || undefined)}
            onOpen={openChange}
            onExpand={() => toggleFold(entry.id)}
          />
        ) : addressed && direct.isError ? (
          <p className="n-body text-n-text-2">This change doesn&apos;t exist, or isn&apos;t in this workspace.</p>
        ) : (
          <AskYourAgent
            label="Or ask your agent"
            prompts={["What changed in this workspace this week, and why?"]}
            className="mt-auto"
          />
        )
      }
    >
      <div className="flex flex-col gap-5">
        {counts && <Header eyebrow={changesEyebrow(counts, filters.who)} className="pb-0" />}
        {none ? (
          <div className="flex flex-col gap-1">
            <h2 className="n-support font-medium text-n-text-1">No changes yet</h2>
            <p className="n-body text-n-text-2">Every change an agent or a person makes will appear here.</p>
          </div>
        ) : (
          <ChangesList
            rows={rows}
            filters={filters}
            counts={counts}
            loops={loops}
            canEdit={canEdit}
            selected={selectedKey}
            open={open}
            now={now}
            hrefFor={(id) => address(filters, id)}
            onFilters={onFilters}
            onSelect={select}
            onToggleFold={toggleFold}
            onUndo={undoRow}
          />
        )}
        {more && <div ref={sentinel} aria-hidden className="h-px" />}
      </div>
    </ObjectPage>
  );
}
