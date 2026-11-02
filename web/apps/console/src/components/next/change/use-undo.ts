"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { changes } from "@/lib/api/changes";
import { queryKeys } from "@/lib/api/query-keys";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { refusalOf, type Refusal } from "@/lib/change/refusal";

export function useUndo({ onUndone }: { onUndone?: () => void } = {}) {
  const queryClient = useQueryClient();
  const showError = useApiErrorToast();
  const [refused, setRefused] = useState<{ id: string; refusal: Refusal } | null>(null);

  const mutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => changes.undo(id, reason),
    onSuccess: () => {
      setRefused(null);
      onUndone?.();
    },
    // replaces the global toast, so anything but a refusal has to show it itself
    onError: (error, { id }) => {
      const refusal = refusalOf(error);
      if (refusal) setRefused({ id, refusal });
      else showError(error);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.changes.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.loops.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.metrics.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.pins.all });
    },
  });

  return {
    undo: (id: string, reason?: string) => {
      if (!mutation.isPending) mutation.mutate({ id, reason });
    },
    pending: mutation.isPending,
    refusalFor: (id: string) => (refused?.id === id ? refused.refusal : null),
  };
}
