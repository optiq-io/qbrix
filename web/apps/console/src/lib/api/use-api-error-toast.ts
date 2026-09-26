"use client";

import { useCallback } from "react";
import { useToast } from "@qbrix/ui/components/toast";
import { resolveApiError } from "./handle-error";

export function useApiErrorToast() {
  const toast = useToast();

  return useCallback(
    (err: unknown, fallback?: string) => {
      const resolved = resolveApiError(err, fallback);
      toast.errorRich({
        title: resolved.title,
        message: resolved.message,
        hint: resolved.hint,
        action: resolved.action,
      });
    },
    [toast],
  );
}
