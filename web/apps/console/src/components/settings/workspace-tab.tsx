"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2 } from "lucide-react";
import { ErrorState } from "@qbrix/ui/components/error-state";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { useToast } from "@qbrix/ui/components/toast";
import { auth } from "@/lib/api/auth";
import { queryKeys } from "@/lib/api/query-keys";
import { apiErrorCode } from "@/lib/api/handle-error";
import { useAuth } from "@/lib/auth/context";
import { useEntitlements } from "@/lib/entitlements";
import { planLabel } from "@/lib/edition";
import {
  SettingsHead,
  FactStrip,
  Fact,
  FieldRow,
  Chip,
  fieldInput,
  btnPrimary,
  formatDay,
  capLabel,
} from "./chrome";

// board `APP · Settings / Workspace`. the org's identity only — who is in it
// moved to the Members tab, which the console IA on board `02 · Sitemap &
// Handoff` has always listed and the code never split out.
//
// `PATCH /auth/workspace` returns `member_count=0` hardcoded, so the response
// is never written into the cache; the row is invalidated and refetched
// instead. writing it through would zero the members fact on every rename.

export function WorkspaceTab() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { isCloud } = useEntitlements();

  const [name, setName] = useState<string | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const workspaceQuery = useQuery({
    queryKey: queryKeys.workspace.current,
    queryFn: () => auth.getWorkspace(),
  });
  const workspace = workspaceQuery.data;

  const isAdmin = user?.role === "admin";

  const save = useMutation({
    mutationFn: () =>
      auth.updateWorkspace({
        name: (name ?? workspace?.name ?? "").trim(),
        ...(slug !== null && slug.trim() !== workspace?.slug
          ? { slug: slug.trim() }
          : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspace.all });
      setName(null);
      setSlug(null);
      toast.success("Workspace updated");
    },
  });

  if (workspaceQuery.isPending) {
    return (
      <div className="flex flex-1 flex-col">
        <div className="flex flex-col gap-2.5 border-b border-border-subtle px-7 py-5">
          <Skeleton className="h-[22px] w-40" />
          <Skeleton className="h-4 w-[560px] max-w-full" />
        </div>
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="flex h-[113px] items-center border-b border-border-subtle px-7"
          >
            <Skeleton className="h-4 w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (workspaceQuery.isError || !workspace) {
    return (
      <ErrorState
        title="Couldn't load the workspace"
        description="Your account and the rest of settings are unaffected."
        code={apiErrorCode(workspaceQuery.error)}
        onRetry={() => workspaceQuery.refetch()}
      />
    );
  }

  const draftName = name ?? workspace.name;
  const draftSlug = slug ?? workspace.slug;
  const dirty =
    (draftName.trim() !== workspace.name && draftName.trim() !== "") ||
    (draftSlug.trim() !== workspace.slug && draftSlug.trim() !== "");

  async function copyId() {
    if (!workspace) return;
    try {
      await navigator.clipboard.writeText(workspace.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast.error("Couldn't copy to the clipboard");
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <SettingsHead
        title="Workspace"
        description={
          <>
            How this organization is identified across the console, in invites
            and in every API response.
            {!isAdmin && " Only workspace admins can change it."}
          </>
        }
        meta={
          <>
            <span className="text-[15px] font-medium text-text-primary">
              {workspace.name}
            </span>
            {user?.plan_tier && (
              <span className="text-[13px] text-text-faint">
                {`${planLabel(user.plan_tier)} plan`}
              </span>
            )}
          </>
        }
      />

      <FactStrip>
        <Fact label="Members" value={workspace.member_count} />
        <Fact
          label="Seats"
          value={user?.usage?.seats ?? "—"}
          sub={capLabel(user?.limits?.max_seats)}
        />
        <Fact
          label="Active experiments"
          value={user?.usage?.active_experiments ?? "—"}
          sub={capLabel(user?.limits?.max_active_experiments)}
        />
        <Fact label="Created" value={formatDay(workspace.created_at)} />
      </FactStrip>

      <FieldRow
        label="Name"
        description="Shown in the workspace switcher and on every invite you send."
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <input
            type="text"
            aria-label="Workspace name"
            value={draftName}
            disabled={!isAdmin}
            onChange={(e) => setName(e.target.value)}
            className={fieldInput}
          />
          {isAdmin && (
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={!dirty || save.isPending}
              className={btnPrimary}
            >
              {save.isPending && <Loader2 size={14} className="animate-spin" />}
              Save
            </button>
          )}
        </div>
      </FieldRow>

      <FieldRow
        label="Slug"
        description="Identifies the workspace in URLs. Changing it breaks any link that uses the old one."
      >
        <input
          type="text"
          aria-label="Workspace slug"
          value={draftSlug}
          disabled={!isAdmin}
          onChange={(e) => setSlug(e.target.value)}
          className={`${fieldInput} font-mono`}
        />
      </FieldRow>

      <FieldRow
        label="Workspace ID"
        description="Quote this when you contact support, or when filtering events by tenant."
      >
        <div className="flex items-center gap-2 pt-2">
          <span className="font-mono text-[14px] text-text-secondary">
            {workspace.id}
          </span>
          <button
            type="button"
            onClick={copyId}
            aria-label="Copy workspace ID"
            className="flex size-7 items-center justify-center rounded-lg text-text-faint transition-colors hover:bg-bg-hover hover:text-text-primary"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
      </FieldRow>

      {/* ee builds only; the feature is not built. the chip does not vary by
          tier — below Scale this was once a button reading "available on the
          Scale plan" that routed to billing, so a Growth workspace was upsold
          to Scale for a feature the same card calls coming soon once they had
          paid for it. */}
      {isCloud && (
        <FieldRow
          label="Single sign-on"
          description="Authenticate your team through your own identity provider. Included on the Scale plan."
        >
          <div className="pt-2">
            <Chip>coming soon</Chip>
          </div>
        </FieldRow>
      )}
    </div>
  );
}
