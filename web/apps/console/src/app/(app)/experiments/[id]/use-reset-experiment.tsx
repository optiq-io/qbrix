"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { useToast } from "@qbrix/ui/components/toast";
import { queryKeys } from "@/lib/api/query-keys";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";

// "Reset beliefs" reaches the user from two places — the workspace overflow
// menu (every tab) and the Arms footer card the board draws. one action, one
// name, one confirm flow; the hook exists so the second entry point is not a
// second implementation that could drift.
export function useResetExperiment(id: string) {
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const toastApiError = useApiErrorToast();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => experimentsApi.reset(id),
    onSuccess: (updated) => {
      setOpen(false);
      toast.success("Beliefs reset");
      queryClient.setQueryData(queryKeys.experiments.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.insights.arms(id) });
      queryClient.invalidateQueries({
        queryKey: queryKeys.insights.experiment(id),
      });
    },
    onError: (err) => toastApiError(err, "Failed to reset beliefs"),
  });

  const dialog = (
    <ConfirmDialog
      open={open}
      onClose={() => setOpen(false)}
      onConfirm={() => mutation.mutate()}
      title="Reset beliefs"
      message="This clears the accumulated evidence and restarts learning from the configured prior. Selection history is unaffected. This action cannot be undone."
      confirmLabel="Reset beliefs"
      loadingLabel="Resetting…"
      loading={mutation.isPending}
    />
  );

  return { open: () => setOpen(true), dialog };
}
