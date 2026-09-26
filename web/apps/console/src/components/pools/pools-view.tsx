"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHead } from "@qbrix/ui/components/page-head";
import { OverflowMenu } from "@qbrix/ui/components/overflow-menu";
import { ColumnBar, DataRow, Cell } from "@qbrix/ui/components/data-table";
import type { Column } from "@qbrix/ui/components/data-table";
import { vizSeries } from "@qbrix/ui/components/belief-viz";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { PageReveal } from "@qbrix/ui/components/page-reveal";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { EmptyState } from "@qbrix/ui/components/empty-state";
import { PoolsEmptyIcon } from "@qbrix/ui/components/empty-icons";
import { useToast } from "@qbrix/ui/components/toast";
import { cn } from "@qbrix/ui/lib/utils";
import { pools as poolsApi } from "@/lib/api/pools";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import type { Pool } from "@/lib/api/types";
import { EditPoolDialog } from "@/components/pools/edit-pool-dialog";
import { PoolDraftRow } from "@/components/pools/pool-draft-row";
import { routes, docsUrl } from "@/config/routes";
import { ErrorState } from "@qbrix/ui/components/error-state";
import { apiErrorCode } from "@/lib/api/handle-error";

// board `APP · Pools`. the list sits on the page ground — no panel — which is
// the same treatment as Home and the experiment tabs. the `$bg-raised` panel on
// the empty-states board predates the v3 surface rule; this page is where that
// was settled.
//
// the ARMS column is a *count*. the board's header was renamed from REWARD TYPE
// to ARMS but its cell still draws a reward-type pill — reward type has no field
// on Pool and is a banned readout, so the rename is the intent and the cell is
// stale. the count is not redundant beside the chips: the chip row truncates.
const COLUMNS: Column[] = [
  { label: "Pool", width: 260 },
  { label: "Variants" },
  { label: "Arms", width: 130 },
  { label: "Experiments", width: 112, align: "right" },
  { label: "Created", width: 112, align: "right" },
  { label: "", width: 64 },
];

const CHIP_LIMIT = 5;

function formatCreated(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function VariantChip({ name, index }: { name: string; index: number }) {
  return (
    <span className="flex shrink-0 items-center gap-[7px] rounded-[14px] bg-white/[0.03] px-2.5 py-1">
      <span className={cn("size-[7px] shrink-0 rounded-full", vizSeries(index))} />
      <span className="text-[13px] text-text-secondary">{name}</span>
    </span>
  );
}

/** `/pools` and `/pools/new` are the same view; the route decides whether it
 *  opens with a draft row. the row is not a modal, so there is nothing to
 *  restore on close — it just goes back to `/pools`. */
export function PoolsView({ draftOpen = false }: { draftOpen?: boolean }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const toastApiError = useApiErrorToast();

  const [editPool, setEditPool] = useState<Pool | null>(null);
  const [deletePool, setDeletePool] = useState<Pool | null>(null);
  const [deleting, setDeleting] = useState(false);

  const poolsQuery = useQuery({
    queryKey: queryKeys.pools.list({ limit: 100 }),
    queryFn: () => poolsApi.list({ limit: 100 }),
  });
  const { data, isError, error, refetch } = poolsQuery;

  // one request, reduced to a map — not one per pool
  const experimentsQuery = useQuery({
    queryKey: queryKeys.experiments.list({ limit: 200 }),
    queryFn: () => experimentsApi.list({ limit: 200 }),
  });
  const experimentList = experimentsQuery.data;

  // the Experiments column is fed by the second query, so before this the rows
  // landed and then their counts filled in a beat later — the same staged fill
  // Home had, one column wide.
  const ready = usePageReady([poolsQuery, experimentsQuery]);

  const expCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of experimentList?.experiments ?? []) {
      m.set(e.pool_id, (m.get(e.pool_id) ?? 0) + 1);
    }
    return m;
  }, [experimentList]);

  const pools = data?.pools ?? [];

  async function handleDelete() {
    if (!deletePool) return;
    setDeleting(true);
    try {
      await poolsApi.delete(deletePool.id);
      queryClient.invalidateQueries({ queryKey: queryKeys.pools.all });
      toast.success("Pool deleted");
      setDeletePool(null);
    } catch (err) {
      toastApiError(err, "Failed to delete pool");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <PageHead
        title="Pools"
        meta="A pool is a named set of variants. Experiments point at a pool."
        action={
          draftOpen ? undefined : (
            <Link
              href={routes.newPool}
              className="flex h-9 shrink-0 items-center rounded-full bg-accent px-4 text-[14.5px] font-semibold text-bg transition-colors hover:bg-accent/90"
            >
              New pool
            </Link>
          )
        }
      />

      {/* the head above owes nothing to a request, so it is already drawn —
          only the table waits, and it waits as one thing */}
      <PageReveal
        ready={ready}
        className="flex flex-1 flex-col"
        skeleton={
          <>
            <ColumnBar columns={COLUMNS} />
            {[0, 1, 2].map((i) => (
              <DataRow key={i} height={74}>
                <Cell width={260}>
                  <Skeleton className="h-4 w-32" />
                </Cell>
                <Cell>
                  <Skeleton className="h-6 w-64 rounded-full" />
                </Cell>
                <Cell width={130}>
                  <Skeleton className="h-4 w-8" />
                </Cell>
                <Cell width={112} align="right">
                  <Skeleton className="ml-auto h-4 w-6" />
                </Cell>
                <Cell width={112} align="right">
                  <Skeleton className="ml-auto h-4 w-20" />
                </Cell>
                <Cell width={64} />
              </DataRow>
            ))}
          </>
        }
      >
      {isError ? (
        <ErrorState
          title="Couldn't load pools"
          description="The request to the API failed. This is usually transient — nothing has been lost."
          code={apiErrorCode(error)}
          onRetry={() => refetch()}
        />
      ) : pools.length === 0 && !draftOpen ? (
        <EmptyState
          icon={<PoolsEmptyIcon />}
          title="No pools yet"
          description="A pool is the set of variants qbrix chooses between. Create one, then point an experiment at it."
          secondaryAction={{
            label: "About pools",
            href: docsUrl("pools-and-experiments"),
            external: true,
          }}
        />
      ) : (
        <>
          <ColumnBar columns={COLUMNS} />

          {draftOpen && (
            <PoolDraftRow
              onCancel={() => router.push(routes.pools)}
              onCreated={() => {
                queryClient.invalidateQueries({ queryKey: queryKeys.pools.all });
                router.push(routes.pools);
              }}
            />
          )}

          {pools.map((pool) => {
            const shown = pool.arms.slice(0, CHIP_LIMIT);
            const rest = pool.arms.length - shown.length;
            return (
              <DataRow key={pool.id} height={74} className="group">
                <Cell width={260}>
                  <span className="truncate text-[15px] font-medium text-text-primary">
                    {pool.name}
                  </span>
                </Cell>

                <Cell>
                  <div className="flex items-center gap-2 overflow-hidden">
                    {shown.map((arm) => (
                      <VariantChip key={arm.id} name={arm.name} index={arm.index} />
                    ))}
                    {rest > 0 && (
                      <span className="shrink-0 text-[13px] text-text-faint">
                        +{rest}
                      </span>
                    )}
                    {pool.arms.length === 0 && (
                      <span className="text-[13px] text-text-faint">No variants</span>
                    )}
                  </div>
                </Cell>

                <Cell width={130}>
                  <span className="font-mono text-[13px] tracking-[0.3px] text-text-dim">
                    {pool.arms.length}
                  </span>
                </Cell>

                <Cell width={112} align="right">
                  <span className="font-mono text-[15px] tracking-[0.3px] text-text-primary">
                    {expCounts.get(pool.id) ?? 0}
                  </span>
                </Cell>

                <Cell width={112} align="right">
                  <span className="text-[13px] text-text-faint">
                    {formatCreated(pool.created_at)}
                  </span>
                </Cell>

                <Cell width={64} clip={false}>
                  {/* undrawn, but rename and delete have no other route in
                      the console — same call as the experiment header */}
                  <div className="flex justify-end">
                    <OverflowMenu
                      label={`Actions for ${pool.name}`}
                      hideUntilHover
                      items={[
                        { label: "Rename", onSelect: () => setEditPool(pool) },
                        { label: "Delete", tone: "danger", onSelect: () => setDeletePool(pool) },
                      ]}
                    />
                  </div>
                </Cell>
              </DataRow>
            );
          })}
        </>
      )}
      </PageReveal>

      {editPool && (
        <EditPoolDialog
          open={!!editPool}
          onClose={() => setEditPool(null)}
          pool={editPool}
          onSaved={() => {
            queryClient.invalidateQueries({ queryKey: queryKeys.pools.all });
            setEditPool(null);
            toast.success("Pool updated");
          }}
        />
      )}

      <ConfirmDialog
        open={!!deletePool}
        onClose={() => setDeletePool(null)}
        onConfirm={handleDelete}
        title="Delete pool"
        message="This permanently deletes the pool and its variants. Experiments pointing at it will be affected. This cannot be undone."
        confirmLabel="Delete pool"
        loadingLabel="Deleting…"
        loading={deleting}
      />
    </div>
  );
}
