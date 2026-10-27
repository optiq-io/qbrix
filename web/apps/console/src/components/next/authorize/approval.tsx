"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { auth } from "@/lib/api/auth";
import { connections } from "@/lib/api/connections";
import { usePageReady } from "@/lib/api/page-ready";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError } from "@/lib/api/types";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { useAuth } from "@/lib/auth/context";
import { ApprovalCard } from "./approval-card";
import {
  AuthorizeDone,
  AuthorizeExpired,
  AuthorizeLoading,
  AuthorizeUnavailable,
} from "./frame";

function isAnswered(err: unknown): boolean {
  return err instanceof ApiError && err.code === "OAUTH_REQUEST_NOT_FOUND";
}

export function Approval({ requestId }: { requestId: string }) {
  const { user } = useAuth();
  const toastError = useApiErrorToast();
  const [answered, setAnswered] = useState(false);
  const [decided, setDecided] = useState<boolean | null>(null);

  const request = useQuery({
    queryKey: queryKeys.connections.request(requestId),
    queryFn: () => connections.getRequest(requestId),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const workspace = useQuery({
    queryKey: queryKeys.workspace.current,
    queryFn: auth.getWorkspace,
  });

  const decide = useMutation({
    mutationFn: (approve: boolean) => connections.decide(requestId, approve),
    onSuccess: ({ redirect_to }, approve) => {
      setDecided(approve);
      window.location.assign(redirect_to);
    },
    onError: (err) => {
      if (isAnswered(err)) setAnswered(true);
      else toastError(err);
    },
  });

  const ready = usePageReady([request, workspace]);
  const client = request.data?.client.name;

  if (!ready || !user) return <AuthorizeLoading />;
  if (decided !== null && client) {
    return <AuthorizeDone client={client} approved={decided} workspace={workspace.data?.name} />;
  }
  if (answered || isAnswered(request.error)) return <AuthorizeExpired client={client} />;
  if (!request.data) return <AuthorizeUnavailable onRetry={() => request.refetch()} />;

  return (
    <ApprovalCard
      request={request.data}
      workspace={workspace.data?.name ?? "your workspace"}
      role={user.role}
      pending={decide.isPending}
      onDecide={(approve) => decide.mutate(approve)}
    />
  );
}
