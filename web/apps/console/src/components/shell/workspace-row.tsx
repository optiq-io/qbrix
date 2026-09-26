"use client";

import { useQuery } from "@tanstack/react-query";
import { PanelLeft } from "lucide-react";
import { QbrixBrick } from "@qbrix/ui/components/logo";
import { auth } from "@/lib/api/auth";
import { queryKeys } from "@/lib/api/query-keys";
import { useAuth } from "@/lib/auth/context";

// shared for the same reason as the health poll — the desktop panel and the
// mobile sheet both stay mounted, and both render this row.
export function useWorkspaceName(): string | null {
  const { user } = useAuth();
  const { data, isError } = useQuery({
    queryKey: queryKeys.workspace.current,
    queryFn: () => auth.getWorkspace(),
    enabled: !!user,
    staleTime: 5 * 60_000,
  });

  if (data) return data.name || data.slug;
  if (isError && user) return user.email.split("@")[0];
  return null;
}

// board `Console Shell` / Sidebar / Workspace: mark, org name, collapse. the
// chevrons-up-down glyph beside the name is drawn but disabled — there is no
// workspace switcher, a person belongs to exactly one tenant.
export function WorkspaceRow({
  onCollapse,
  collapseLabel = "Collapse sidebar",
}: {
  onCollapse?: () => void;
  collapseLabel?: string;
}) {
  const label = useWorkspaceName();

  return (
    <div className="flex h-[42px] items-center gap-[11px] rounded-[10px] px-[10px]">
      <QbrixBrick size={26} />
      <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-text-primary">
        {label ?? "workspace"}
      </span>
      {onCollapse ? (
        <button
          type="button"
          onClick={onCollapse}
          aria-label={collapseLabel}
          title={collapseLabel}
          className="flex size-7 shrink-0 items-center justify-center rounded-lg text-text-dim transition-colors hover:bg-bg-hover hover:text-text-secondary"
        >
          <PanelLeft size={17} />
        </button>
      ) : null}
    </div>
  );
}
