"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnBar, DataRow, Cell } from "@qbrix/ui/components/data-table";
import type { Column } from "@qbrix/ui/components/data-table";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { ErrorState } from "@qbrix/ui/components/error-state";
import { OverflowMenu } from "@qbrix/ui/components/overflow-menu";
import type { OverflowItem } from "@qbrix/ui/components/overflow-menu";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { useToast } from "@qbrix/ui/components/toast";
import { auth } from "@/lib/api/auth";
import { queryKeys } from "@/lib/api/query-keys";
import { apiErrorCode } from "@/lib/api/handle-error";
import { useAuth } from "@/lib/auth/context";
import { useEntitlements } from "@/lib/entitlements";
import { RoleUpgradeNote, planLabel } from "@/lib/edition";
import type { Invite, User } from "@/lib/api/types";
import { InviteDialog } from "./invite-dialog";
import {
  SettingsHead,
  FactStrip,
  Fact,
  SubHead,
  Chip,
  formatDay,
  capLabel,
} from "./chrome";

// board `APP · Settings / Members`. replaces the old Admin tab and the member
// table that Workspace also carried — the same people were listed twice, in
// two different geometries, one of them read-only.
//
// it reads `/auth/workspace/members`, not the admin-only `/auth/users`. both
// are tenant-scoped and return the same shape, but members is open to every
// role, and this tab is one the whole workspace can see. that costs the
// server-side `search` filter `/auth/users` offers; the seat cap keeps this
// list short enough that no filter is drawn.
//
// role counts are derived from the rows rather than read from
// `/auth/users/stats` — the stats route is admin-only, and a viewer would get
// a strip of dashes above a list that plainly contradicts it.
//
// what the board does not draw, because nothing can fill it: removing a
// member. there is no delete-user route, and inventing one in the UI would be
// a button that 404s. deactivating revokes access, which is the real mechanism.

const MEMBER_COLUMNS: Column[] = [
  { label: "Member" },
  { label: "Role", width: 160 },
  { label: "Status", width: 120 },
  { label: "Joined", width: 120, align: "right" },
  { label: "", width: 50 },
];

const INVITE_COLUMNS: Column[] = [
  { label: "Email" },
  { label: "Role", width: 160 },
  { label: "Invited by", width: 120 },
  { label: "Expires", width: 120, align: "right" },
  { label: " ", width: 50 },
];

const ROLES = ["admin", "member", "viewer"] as const;

const ROLE_BLURB: Record<string, string> = {
  admin: "billing, roles, workspace",
  member: "create and run experiments",
  viewer: "read-only across the console",
};

function initialsOf(user: User): string {
  return (user.name || user.email.split("@")[0])
    .split(/[\s.]+/)
    .map((part) => part[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

/** "in 5 days" / "expired" — an absolute date says nothing about urgency */
function expiryLabel(seconds: number): string {
  const days = Math.ceil((seconds * 1000 - Date.now()) / 86_400_000);
  if (days <= 0) return "expired";
  return days === 1 ? "in 1 day" : `in ${days} days`;
}

export function MembersTab({
  inviteOpen,
  onCloseInvite,
}: {
  /** owned by the page head, which is where the board draws the action */
  inviteOpen: boolean;
  onCloseInvite: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { hasRBAC } = useEntitlements();

  const [statusTarget, setStatusTarget] = useState<User | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<Invite | null>(null);

  const isAdmin = user?.role === "admin";

  const membersQuery = useQuery({
    queryKey: queryKeys.workspace.members(),
    queryFn: () => auth.listMembers(),
  });

  // admin-only route: a member asking for it gets a 403, which the global
  // mutation handler would not catch and the list would render as an error
  const invitesQuery = useQuery({
    queryKey: queryKeys.workspace.invites(),
    queryFn: () => auth.listInvites(),
    enabled: isAdmin,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.workspace.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
  };

  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) =>
      auth.updateUserRole(id, role),
    onSuccess: (_data, variables) => {
      invalidate();
      toast.success(`Role changed to ${variables.role}`);
    },
  });

  const changeStatus = useMutation({
    mutationFn: (target: User) =>
      auth.updateUserStatus(target.id, { is_active: !target.is_active }),
    onSuccess: (_data, target) => {
      setStatusTarget(null);
      invalidate();
      toast.success(target.is_active ? "Member deactivated" : "Member activated");
    },
  });

  const revokeInvite = useMutation({
    mutationFn: (invite: Invite) => auth.revokeInvite(invite.id),
    onSuccess: () => {
      setRevokeTarget(null);
      invalidate();
      toast.success("Invite revoked");
    },
  });

  const members = membersQuery.data?.users ?? [];
  const seatCap = capLabel(user?.limits?.max_seats);
  const invites = (invitesQuery.data?.invites ?? []).filter(
    (invite) => invite.status === "pending",
  );

  const counts = ROLES.map(
    (role) => members.filter((m) => m.role === role).length,
  );

  return (
    <div className="flex flex-1 flex-col">
      <SettingsHead
        title="Members"
        description={
          <>
            Everyone with access to this workspace, and the invites still
            outstanding. A role decides what a member can change; deactivating
            one revokes access without deleting their work.
            {!isAdmin && " Only workspace admins can invite or change members."}
          </>
        }
        meta={
          <>
            <span className="text-[13.5px] text-text-dim">
              {user?.usage?.seats ?? members.length}
              {seatCap ? ` ${seatCap}` : ""} seats
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
        {ROLES.map((role, i) => (
          <Fact
            key={role}
            label={role}
            value={membersQuery.isPending ? "—" : counts[i]}
            sub={ROLE_BLURB[role]}
          />
        ))}
        <Fact
          label="Pending invites"
          value={isAdmin ? (invitesQuery.isPending ? "—" : invites.length) : "—"}
          sub={isAdmin ? "not yet accepted" : "admins only"}
        />
      </FactStrip>

      <ColumnBar columns={MEMBER_COLUMNS} gap={18} divideTop={false} />

      {membersQuery.isPending ? (
        [0, 1, 2].map((i) => (
          <div
            key={i}
            className="flex h-16 items-center border-b border-border-subtle px-7"
          >
            <Skeleton className="h-4 w-full" />
          </div>
        ))
      ) : membersQuery.isError ? (
        <ErrorState
          title="Couldn't load members"
          description="Your own account and the rest of settings are unaffected."
          code={apiErrorCode(membersQuery.error)}
          onRetry={() => membersQuery.refetch()}
        />
      ) : (
        members.map((member) => {
          const isSelf = member.id === user?.id;

          const items: OverflowItem[] = [];
          if (hasRBAC) {
            for (const role of ROLES) {
              if (role === member.role) continue;
              items.push({
                label: `Make ${role}`,
                onSelect: () => changeRole.mutate({ id: member.id, role }),
              });
            }
          }
          items.push(
            member.is_active
              ? {
                  label: "Deactivate",
                  tone: "danger",
                  onSelect: () => setStatusTarget(member),
                }
              : { label: "Activate", onSelect: () => setStatusTarget(member) },
          );

          return (
            <DataRow key={member.id} height={64} gap={18} className="group">
              <Cell>
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex size-[30px] shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-[11.5px] font-semibold text-text-secondary">
                    {initialsOf(member)}
                  </div>
                  <div className="flex min-w-0 flex-col gap-[3px]">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-[14.5px] text-text-primary">
                        {member.name || member.email.split("@")[0]}
                      </span>
                      {isSelf && (
                        <span className="shrink-0 text-[12.5px] text-text-faint">
                          you
                        </span>
                      )}
                    </div>
                    <span className="truncate font-mono text-[12px] text-text-faint">
                      {member.email}
                    </span>
                  </div>
                </div>
              </Cell>

              <Cell width={160}>
                <Chip tone={member.role === "admin" ? "accent" : "default"}>
                  {member.role}
                </Chip>
              </Cell>

              <Cell width={120}>
                <span className="flex items-center gap-2">
                  <span
                    className={`size-[6px] shrink-0 rounded-full ${
                      member.is_active ? "bg-positive" : "bg-text-faint"
                    }`}
                  />
                  <span
                    className={`text-[13.5px] ${
                      member.is_active ? "text-text-secondary" : "text-text-faint"
                    }`}
                  >
                    {member.is_active ? "Active" : "Deactivated"}
                  </span>
                </span>
              </Cell>

              <Cell width={120} align="right">
                <span className="text-[13.5px] text-text-faint">
                  {formatDay(member.created_at)}
                </span>
              </Cell>

              <Cell width={50} clip={false} className="flex justify-end">
                {/* the API refuses to change your own status, and role
                    assignment on yourself is how an admin locks themselves out
                    of their own workspace */}
                {isAdmin && !isSelf && (
                  <OverflowMenu hideUntilHover items={items} />
                )}
              </Cell>
            </DataRow>
          );
        })
      )}

      {isAdmin && (
        <>
          <SubHead
            title="Pending invites"
            description="An invite expires after 7 days. Revoking one makes its link dead immediately."
          />

          <ColumnBar columns={INVITE_COLUMNS} gap={18} divideTop={false} />

          {invitesQuery.isPending ? (
            <div className="flex h-16 items-center border-b border-border-subtle px-7">
              <Skeleton className="h-4 w-full" />
            </div>
          ) : invitesQuery.isError ? (
            <ErrorState
              title="Couldn't load invites"
              description="The member list above is unaffected."
              code={apiErrorCode(invitesQuery.error)}
              onRetry={() => invitesQuery.refetch()}
            />
          ) : invites.length === 0 ? (
            <div className="flex flex-col items-center gap-1.5 py-16">
              <p className="text-[15px] text-text-secondary">
                No invites outstanding
              </p>
              <p className="text-[14px] text-text-dim">
                Everyone invited has accepted.
              </p>
            </div>
          ) : (
            invites.map((invite) => (
              <DataRow key={invite.id} height={64} gap={18} className="group">
                <Cell>
                  <span className="truncate text-[14.5px] text-text-primary">
                    {invite.email}
                  </span>
                </Cell>

                <Cell width={160}>
                  <Chip tone={invite.role === "admin" ? "accent" : "default"}>
                    {invite.role}
                  </Chip>
                </Cell>

                <Cell width={120}>
                  <span className="text-[13.5px] text-text-faint">
                    {members.find((m) => m.id === invite.invited_by)?.name ??
                      "—"}
                  </span>
                </Cell>

                <Cell width={120} align="right">
                  <span className="text-[13.5px] text-amber">
                    {expiryLabel(invite.expires_at)}
                  </span>
                </Cell>

                <Cell width={50} clip={false} className="flex justify-end">
                  <OverflowMenu
                    hideUntilHover
                    items={[
                      {
                        label: "Revoke invite",
                        tone: "danger",
                        onSelect: () => setRevokeTarget(invite),
                      },
                    ]}
                  />
                </Cell>
              </DataRow>
            ))
          )}
        </>
      )}

      {isAdmin && <RoleUpgradeNote />}

      <InviteDialog
        open={inviteOpen}
        onClose={() => {
          onCloseInvite();
          invalidate();
        }}
        onCreated={invalidate}
      />

      <ConfirmDialog
        open={statusTarget !== null}
        onClose={() => setStatusTarget(null)}
        onConfirm={() => statusTarget && changeStatus.mutate(statusTarget)}
        tone={statusTarget?.is_active ? "danger" : "accent"}
        title={
          statusTarget?.is_active ? "Deactivate member" : "Activate member"
        }
        message={
          statusTarget?.is_active
            ? `${statusTarget?.email} loses access immediately. Everything they created stays, and you can reactivate them at any time.`
            : `${statusTarget?.email} regains access with the role they had before.`
        }
        confirmLabel={statusTarget?.is_active ? "Deactivate" : "Activate"}
        loadingLabel={statusTarget?.is_active ? "Deactivating…" : "Activating…"}
        loading={changeStatus.isPending}
      />

      <ConfirmDialog
        open={revokeTarget !== null}
        onClose={() => setRevokeTarget(null)}
        onConfirm={() => revokeTarget && revokeInvite.mutate(revokeTarget)}
        title="Revoke invite"
        message={`The link sent to ${revokeTarget?.email ?? ""} stops working immediately. You can send a new invite at any time.`}
        confirmLabel="Revoke invite"
        loadingLabel="Revoking…"
        loading={revokeInvite.isPending}
      />
    </div>
  );
}
