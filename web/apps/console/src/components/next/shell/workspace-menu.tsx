"use client";

import { Bell, ChevronsUpDown, Github, KeyRound, Settings, UserPlus, Users } from "lucide-react";
import { useAuth } from "@/lib/auth/context";
import { planLabel } from "@/lib/edition";
import { statusProblem } from "@/lib/workspace/status";
import { settingsHref, workspaceSettingsHome } from "@/components/next/settings/section";
import { useWorkspace, useWorkspaceStatus } from "./data";
import { EndMenu, MenuRow } from "./end-menu";

const ROLE = { admin: "an admin", member: "a member", viewer: "a viewer" } as const;

function plural(count: number, unit: string) {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}

export function WorkspaceMenu() {
  const { user } = useAuth();
  const { data: workspace, isError } = useWorkspace();
  const { data: status } = useWorkspaceStatus();

  const name = workspace ? workspace.name || workspace.slug : isError ? (user?.email.split("@")[0] ?? "") : "";
  const mark = name.charAt(0).toLowerCase();
  const problem = status ? statusProblem(status) : null;
  const who = [
    user?.plan_tier ? planLabel(user.plan_tier) : "Self-hosted",
    workspace && plural(workspace.member_count, "member"),
    user && `you're ${ROLE[user.role]}`,
    status && `v${status.version}`,
  ].filter(Boolean);

  return (
    <EndMenu
      label="Workspace"
      opens="over"
      width={320}
      trigger={
        <>
          <span className="flex size-[22px] shrink-0 items-center justify-center rounded-n-control bg-n-ink text-[12px] font-semibold text-n-on-ink">
            {mark}
          </span>
          <span className="min-w-0 flex-1 truncate n-body font-semibold text-n-text-1">{name}</span>
          <ChevronsUpDown size={15} className="shrink-0 text-n-text-3" />
        </>
      }
    >
      {(close) => (
        <>
          <div className="flex items-center gap-2.5 px-2 pt-2 pb-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-n-panel bg-n-ink text-[15px] font-semibold text-n-on-ink">
              {mark}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate n-body font-semibold text-n-text-1">{name}</span>
              <span className="truncate n-label font-normal text-n-text-3">{who.join(" · ")}</span>
            </span>
          </div>

          {problem && (
            <div role="status" className="mb-1.5 flex items-center gap-2 rounded-n-chip bg-n-fill-1 px-2 py-1.5">
              <span className="size-[7px] shrink-0 rounded-full bg-n-part-fg" />
              <span className="n-meta text-n-part-fg">{problem}</span>
            </div>
          )}

          <MenuRow icon={Settings} label="Workspace settings" hint="G W" mono href={workspaceSettingsHome} close={close} />
          {user?.role === "admin" && (
            <MenuRow icon={UserPlus} label="Invite people" href={settingsHref("workspace", "members")} close={close} />
          )}
          <MenuRow
            icon={Users}
            label="Members"
            hint={workspace?.member_count}
            href={settingsHref("workspace", "members")}
            close={close}
          />
          <MenuRow icon={KeyRound} label="Keys" href={settingsHref("workspace", "keys")} close={close} />
          <MenuRow icon={Bell} label="Alerts" href={settingsHref("workspace", "alerts")} close={close} />
          <MenuRow icon={Github} label="GitHub" href={settingsHref("workspace", "github")} close={close} />
        </>
      )}
    </EndMenu>
  );
}
