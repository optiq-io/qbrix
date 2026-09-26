"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/api/query-keys";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { insights as insightsApi } from "@/lib/api/insights";
import { routes } from "@/config/routes";
import { useEntitlements } from "@/lib/entitlements";
import { WorkspaceTabs } from "@qbrix/ui/components/workspace-tabs";
import type { WorkspaceTabItem } from "@qbrix/ui/components/workspace-tabs";
import { PageHead } from "@qbrix/ui/components/page-head";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { useToast } from "@qbrix/ui/components/toast";
import { cn } from "@qbrix/ui/lib/utils";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import type { Experiment } from "@/lib/api/types";
import { leaderOf } from "./derive";
import { OverflowMenu } from "@qbrix/ui/components/overflow-menu";
import { useResetExperiment } from "./use-reset-experiment";
import { HeaderActionsProvider } from "./header-actions";
import type { PendingEdit } from "./header-actions";

const DAY_MS = 86_400_000;

// board `APP · Experiment / Overview` / Title: h28 pill, 13.5/500 label.
function Chip({
  tone,
  dot,
  children,
}: {
  tone: "positive" | "accent" | "muted";
  dot?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "flex h-7 shrink-0 items-center gap-[7px] rounded-full px-[11px] text-[13.5px] font-medium",
        tone === "positive" && "bg-positive/10 text-positive",
        tone === "accent" && "bg-accent/10 text-accent",
        tone === "muted" && "bg-bg-hover text-text-dim",
      )}
    >
      {dot && (
        <span
          className={cn(
            "size-[7px] rounded-full",
            tone === "positive" ? "bg-positive" : "bg-text-faint",
          )}
        />
      )}
      {children}
    </span>
  );
}

// Pause and Discard — h36 pills on a white/5 ground, per the board's action row.
function GhostPill({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex h-9 shrink-0 items-center rounded-full bg-bg-hover px-4 text-[14.5px] font-medium text-text-primary transition-colors hover:bg-white/[0.09] disabled:pointer-events-none disabled:opacity-50"
    >
      {children}
    </button>
  );
}

const ACCENT_PILL =
  "flex h-9 shrink-0 items-center rounded-full bg-accent px-4 text-[14.5px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:pointer-events-none disabled:opacity-50";

export default function ExperimentWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const toast = useToast();
  const toastApiError = useApiErrorToast();
  const queryClient = useQueryClient();
  const { gate, hasInsights } = useEntitlements();

  const [deleteOpen, setDeleteOpen] = useState(false);
  const reset = useResetExperiment(id);

  const {
    data: experiment,
    isLoading: expLoading,
    isError: expError,
  } = useQuery({
    queryKey: queryKeys.experiments.detail(id),
    queryFn: () => experimentsApi.get(id),
  });

  // shared with the Overview page through the query key — one poll, not two
  const { data: armAnalytics } = useQuery({
    queryKey: queryKeys.insights.arms(id),
    queryFn: () => insightsApi.getArmStats(id),
    enabled: hasInsights,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const { data: expStats } = useQuery({
    queryKey: queryKeys.insights.experiment(id),
    queryFn: () => insightsApi.getStats(id),
    enabled: hasInsights,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const deleteMutation = useMutation({
    mutationFn: () => experimentsApi.delete(id),
    onSuccess: () => {
      setDeleteOpen(false);
      toast.success("Experiment deleted");
      router.push(routes.home);
      queryClient.removeQueries({ queryKey: queryKeys.experiments.detail(id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.experiments.all });
    },
    onError: (err) => toastApiError(err, "Failed to delete experiment"),
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => experimentsApi.update(id, { enabled }),
    onMutate: async (enabled) => {
      await queryClient.cancelQueries({
        queryKey: queryKeys.experiments.detail(id),
      });
      const prev = queryClient.getQueryData<Experiment>(
        queryKeys.experiments.detail(id),
      );
      if (prev) {
        queryClient.setQueryData(queryKeys.experiments.detail(id), {
          ...prev,
          enabled,
        });
      }
      return { prev };
    },
    onError: (_err, _enabled, ctx) => {
      if (ctx?.prev) {
        queryClient.setQueryData(queryKeys.experiments.detail(id), ctx.prev);
      }
      toast.error("Failed to update experiment status");
    },
    onSuccess: (_, variables) => {
      toast.success(variables ? "Experiment resumed" : "Experiment paused");
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.experiments.detail(id),
      });
    },
  });

  // board order: Insights sits before Activity.
  //
  // a *locked* tab is still listed — it leads to the UpgradeCard, which is the
  // only way a growth tenant learns Activity exists. an *absent* one is gone:
  // an OSS build has no tier to sell.
  const tabs: WorkspaceTabItem[] = [
    { label: "Overview", href: routes.experimentOverview(id), exact: true },
    { label: "Arms", href: routes.experimentArms(id) },
    { label: "Policy", href: routes.experimentPolicy(id) },
    { label: "Gate", href: routes.experimentGate(id) },
    ...(gate("insights") !== "absent"
      ? [{ label: "Insights", href: routes.experimentInsights(id) }]
      : []),
    ...(gate("event_log") !== "absent"
      ? [{ label: "Activity", href: routes.experimentActivity(id) }]
      : []),
  ];

  if (expError || (!expLoading && !experiment)) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-32">
        <p className="text-[15px] text-text-dim">Experiment not found</p>
        <Link
          href={routes.home}
          className="text-[14px] font-medium text-accent hover:underline"
        >
          Back to experiments
        </Link>
      </div>
    );
  }

  // "Running · Day 14" — days since the first selection, which is when the
  // experiment actually started doing work, not when the row was created.
  //
  // an experiment with no selections yet reports `first_selection_ms: 0`, not
  // null, so `?? null` let the epoch through and the chip read "Day 20674".
  const rawFirstMs = expStats?.first_selection_ms ?? null;
  const firstMs = rawFirstMs && rawFirstMs > 0 ? rawFirstMs : null;
  const day =
    firstMs !== null ? Math.floor((Date.now() - firstMs) / DAY_MS) + 1 : null;
  const leader = leaderOf(armAnalytics?.arms ?? []);

  // the boards swap the whole action row per tab; a tab with unsaved work
  // (Policy) replaces it with Discard / Save changes until it is clean again.
  const pendingActions = (pending: PendingEdit) => (
    <div className="flex items-center gap-2.5">
      <GhostPill onClick={pending.onDiscard} disabled={pending.saving}>
        Discard
      </GhostPill>
      <button
        type="button"
        onClick={pending.onSave}
        disabled={pending.saving || pending.saveDisabled}
        className={ACCENT_PILL}
      >
        {pending.saving ? "Saving…" : "Save changes"}
      </button>
    </div>
  );

  return (
    <HeaderActionsProvider>
      {({ pending, tool }) => (
    <div className="flex flex-col">
      {expLoading || !experiment ? (
        /* the head this replaces is a 26px title over a 15px meta line, so the
           skeleton reserves both — an `h-8` bar alone left the tabs 25px high
           and they jumped down the moment the experiment resolved */
        <div className="flex flex-col gap-[7px] px-7 pb-[18px] pt-6">
          <Skeleton className="h-[34px] w-64" />
          <Skeleton className="h-[21px] w-40" />
        </div>
      ) : (
        <PageHead
          className="pb-[18px]"
          title={experiment.name}
          adornments={
            <>
              {experiment.enabled ? (
                <Chip tone="positive" dot>
                  {day !== null ? `Running · Day ${day}` : "Running"}
                </Chip>
              ) : (
                <Chip tone="muted" dot>
                  Paused
                </Chip>
              )}
              {leader && <Chip tone="accent">observed leader</Chip>}
            </>
          }
          action={
            pending ? (
              pendingActions(pending)
            ) : (
            <div className="flex items-center gap-2.5">
              {/* a tab's own control (Insights' range selector) sits left of
                  the standard actions rather than replacing them — the boards
                  swap the row per tab, but Pause and Commit are experiment-wide
                  and should not disappear because you opened a tab */}
              {tool}
              <GhostPill
                onClick={() => toggleMutation.mutate(!experiment.enabled)}
                disabled={toggleMutation.isPending}
              >
                {experiment.enabled ? "Pause" : "Resume"}
              </GhostPill>
              <OverflowMenu
                items={[
                  {
                    label: "Reset beliefs",
                    onSelect: reset.open,
                    disabled: experiment.enabled,
                    title: experiment.enabled
                      ? "Pause the experiment to reset its beliefs"
                      : undefined,
                  },
                  {
                    label: "Delete experiment",
                    tone: "danger",
                    onSelect: () => setDeleteOpen(true),
                  },
                ]}
              />
              <Link href={routes.experimentGate(id)} className={ACCENT_PILL}>
                Commit winner
              </Link>
            </div>
            )
          }
        />
      )}

      <div className="flex h-[50px] shrink-0 items-center border-b border-border-subtle px-7">
        {expLoading ? <Skeleton className="h-8 w-80" /> : <WorkspaceTabs items={tabs} />}
      </div>

      {children}

      {/* dialogs — mounted at layout level so they survive tab navigation */}
      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={() => deleteMutation.mutate()}
        title="Delete Experiment"
        message="This will permanently delete this experiment and its configuration. This action cannot be undone."
        confirmLabel="Delete Experiment"
        loading={deleteMutation.isPending}
      />

      {reset.dialog}
    </div>
      )}
    </HeaderActionsProvider>
  );
}
