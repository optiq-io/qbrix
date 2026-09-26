"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnBar, DataRow, Cell } from "@qbrix/ui/components/data-table";
import type { Column } from "@qbrix/ui/components/data-table";
import { OverflowMenu } from "@qbrix/ui/components/overflow-menu";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { useToast } from "@qbrix/ui/components/toast";
import { auth } from "@/lib/api/auth";
import { queryKeys } from "@/lib/api/query-keys";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { useAuth } from "@/lib/auth/context";
import { planLabel } from "@/lib/edition";
import type { APIKey, APIKeyCreateResponse } from "@/lib/api/types";
import { ApiKeySecretDialog } from "./api-key-secret-dialog";
import { RenameApiKeyDialog } from "./rename-api-key-dialog";
import { SettingsHead, formatDay } from "./chrome";

// board `APP · Settings / API Keys` / Note + Cols + Rows. hairline rows on the
// page ground, no card — the surface rule settled on Pools.
//
// four things the board draws are not built, because nothing can fill them:
//   · KEY (`optiq_live_8f2a••••••••4c91` + copy) — the row stores `key_hash`
//     only, a bare SHA-256. there is no prefix and no last-4 to recover, so the
//     column could never identify a key. NAME takes the flex instead.
//   · LAST USED — `APIKeyRepository.update_last_used()` has no caller anywhere,
//     so `last_used_at` is null for every key forever. this one is not merely
//     empty, it is *wrong*: a key in daily production use would read "Never",
//     and someone would revoke a live key on the strength of it.
//   · the status dot on NAME — `list_by_user` filters `is_active`, so a revoked
//     key never comes back and the dot could only ever be green.
//   · the quota progress bar — the fraction is real, but it
//     renders against a cap of 2, where a number says more than a bar.

const COLUMNS: Column[] = [
  { label: "Name" },
  { label: "Scopes", width: 220 },
  { label: "Created", width: 120, align: "right" },
  { label: "", width: 50 },
];

// scopes are not per-key: `create_api_key` copies ROLE_SCOPES[creator.role]
// wholesale, so an admin's key carries twenty of them. twenty do not fit a
// 220px cell and two arbitrary ones say nothing, so the cell states what the
// key can actually do and hangs the literal list off the title.
function accessLevel(scopes: string[]): string {
  if (scopes.includes("system:admin")) return "admin";
  const writes = scopes.some((s) => s.endsWith(":write") || s.endsWith(":delete"));
  return writes ? "read + write" : "read only";
}

export function ApiKeysTab({
  createOpen,
  onCloseCreate,
}: {
  /** owned by the page head, which is where the board draws the action */
  createOpen: boolean;
  onCloseCreate: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const toastApiError = useApiErrorToast();
  const { user, refresh } = useAuth();

  const [renameKey, setRenameKey] = useState<APIKey | null>(null);
  const [rotateKey, setRotateKey] = useState<APIKey | null>(null);
  const [revokeKey, setRevokeKey] = useState<APIKey | null>(null);
  // the plain key exists for exactly one response and is never retrievable
  // again, so it is held here until the panel is dismissed
  const [secret, setSecret] = useState<APIKeyCreateResponse | null>(null);

  const { data: keys, isLoading } = useQuery({
    queryKey: queryKeys.apiKeys.list,
    queryFn: () => auth.listApiKeys(),
  });

  // the list comes from react-query, the workspace count from the profile on
  // the auth context — both, or the fraction goes stale against its own list
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.all });
    void refresh();
  };

  const createMutation = useMutation({
    mutationFn: (name: string) => auth.createApiKey({ name }),
    onSuccess: (result) => {
      setSecret(result);
      onCloseCreate();
      invalidate();
    },
    onError: (err) => toastApiError(err, "Failed to create API key"),
  });

  const rotateMutation = useMutation({
    mutationFn: (id: string) => auth.rotateApiKey(id),
    onSuccess: (result) => {
      setRotateKey(null);
      setSecret(result);
      invalidate();
    },
    onError: (err) => toastApiError(err, "Failed to rotate API key"),
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      auth.updateApiKey(id, { name }),
    onSuccess: () => {
      setRenameKey(null);
      toast.success("API key renamed");
      invalidate();
    },
    onError: (err) => toastApiError(err, "Failed to rename API key"),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => auth.deleteApiKey(id),
    onSuccess: () => {
      setRevokeKey(null);
      toast.success("API key revoked");
      invalidate();
    },
    onError: (err) => toastApiError(err, "Failed to revoke API key"),
  });

  const rows = keys ?? [];

  const cap = user?.limits?.max_api_keys;
  const capped = cap !== undefined && cap !== -1;
  const workspaceCount = user?.usage?.api_keys;
  const used = workspaceCount ?? rows.length;
  const noun = used === 1 ? "key" : "keys";

  // the count is workspace-wide but `rows` is the caller's own, so it has to
  // name its scope — "2 keys" over one visible row reads as a bug
  const countLabel =
    workspaceCount === undefined
      ? `${used} active ${noun}`
      : capped
        ? `${used} of ${cap} in this workspace`
        : `${used} ${noun} in this workspace`;

  return (
    <div className="flex flex-1 flex-col">
      <SettingsHead
        title="API keys"
        // the board's copy says to "scope each key to the environment it
        // serves" — there is no per-key scope picker, and a key inherits its
        // creator's role scopes, so that sentence would be a lie
        description="A key is shown once at creation and stored as a SHA-256 hash — it cannot be shown or recovered later. Each key carries the scopes of the member who created it, and revoking one takes effect immediately."
        meta={
          <>
            <span className="text-[13.5px] text-text-dim">
              {isLoading ? "—" : countLabel}
            </span>
            {user?.plan_tier && (
              <span className="text-[13px] text-text-faint">
                {`${planLabel(user.plan_tier)} plan`}
              </span>
            )}
          </>
        }
      />

      <ColumnBar columns={COLUMNS} gap={18} divideTop={false} />

      {isLoading ? (
        [0, 1, 2].map((i) => (
          <div
            key={i}
            className="flex h-16 items-center border-b border-border-subtle px-7"
          >
            <Skeleton className="h-4 w-full" />
          </div>
        ))
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 py-24">
          <p className="text-[15px] text-text-secondary">No API keys</p>
          <p className="text-[14px] text-text-dim">
            Create one to reach the API from your own services.
          </p>
        </div>
      ) : (
        rows.map((key) => (
          <DataRow key={key.id} height={64} gap={18} className="group">
            <Cell>
              <span className="truncate text-[14.5px] text-text-primary">
                {key.name}
              </span>
            </Cell>

            <Cell width={220}>
              <span
                title={key.scopes.join(", ")}
                className="inline-flex h-6 items-center rounded-xl border border-border-subtle bg-white/[0.03] px-2.5 text-[12.5px] text-text-dim"
              >
                {accessLevel(key.scopes)}
              </span>
            </Cell>

            <Cell width={120} align="right">
              <span className="text-[13.5px] text-text-faint">
                {formatDay(key.created_at)}
              </span>
            </Cell>

            <Cell width={50} clip={false} className="flex justify-end">
              <OverflowMenu
                hideUntilHover
                items={[
                  { label: "Rename", onSelect: () => setRenameKey(key) },
                  { label: "Rotate key", onSelect: () => setRotateKey(key) },
                  {
                    label: "Revoke key",
                    tone: "danger",
                    onSelect: () => setRevokeKey(key),
                  },
                ]}
              />
            </Cell>
          </DataRow>
        ))
      )}

      <ApiKeySecretDialog
        open={createOpen || secret !== null}
        secret={secret}
        creating={createMutation.isPending}
        onCreate={(name) => createMutation.mutate(name)}
        onClose={() => {
          setSecret(null);
          onCloseCreate();
        }}
      />

      {renameKey && (
        <RenameApiKeyDialog
          apiKey={renameKey}
          saving={renameMutation.isPending}
          onSave={(name) => renameMutation.mutate({ id: renameKey.id, name })}
          onClose={() => setRenameKey(null)}
        />
      )}

      <ConfirmDialog
        open={rotateKey !== null}
        onClose={() => setRotateKey(null)}
        onConfirm={() => rotateKey && rotateMutation.mutate(rotateKey.id)}
        tone="accent"
        title="Rotate API key"
        message={`"${rotateKey?.name ?? ""}" will be issued a new secret and the current one stops working immediately. The new key is shown once.`}
        confirmLabel="Rotate key"
        loadingLabel="Rotating…"
        loading={rotateMutation.isPending}
      />

      <ConfirmDialog
        open={revokeKey !== null}
        onClose={() => setRevokeKey(null)}
        onConfirm={() => revokeKey && revokeMutation.mutate(revokeKey.id)}
        title="Revoke API key"
        message={`"${revokeKey?.name ?? ""}" stops working immediately and is removed from this list. This cannot be undone.`}
        confirmLabel="Revoke key"
        loadingLabel="Revoking…"
        loading={revokeMutation.isPending}
      />
    </div>
  );
}
