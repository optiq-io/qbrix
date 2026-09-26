"use client";

import { Suspense, useState, useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { useEntitlements } from "@/lib/entitlements";
import { PageHead } from "@qbrix/ui/components/page-head";
import { tabPillClass } from "@qbrix/ui/components/workspace-tabs";
import { ProfileTab } from "@/components/settings/profile-tab";
import { ApiKeysTab } from "@/components/settings/api-keys-tab";
import { WorkspaceTab } from "@/components/settings/workspace-tab";
import { MembersTab } from "@/components/settings/members-tab";
import { BillingTab } from "@/lib/edition";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes } from "@/config/routes";

// boards `APP · Settings / Profile`, `/ API Keys`, `/ Workspace`,
// `/ Members`. head + a pill tab bar on a hairline, the same chrome the
// experiment workspace uses.
//
// the tab list is the console IA on board `02 · Sitemap & Handoff`: Profile ·
// API keys · Workspace · Members · Billing. Members is not a new surface, it
// is the old Admin tab merged with the member table Workspace also carried —
// the same people, listed twice, in two geometries. Admin is retired; its role
// counts are the fact strip at the top of Members.
//
// Members is deliberately not admin-gated. `/auth/workspace/members` is open
// to every role and a viewer has a real reason to see who is in the workspace;
// only the mutating controls check `isAdmin`, and role assignment checks the
// RBAC tier on top of that.
//
// selection stays on `?tab=` rather than becoming nested routes: it is what
// `routes.settingsApiKeys` and the `/settings/billing` redirect resolve to.
// the console IA lists `/settings/billing`, and that URL
// keeps working as a redirect, but promoting one tab to a real route would
// leave the tab bar driving two navigation mechanisms at once.

type SettingsTab =
  | "profile"
  | "api-keys"
  | "workspace"
  | "members"
  | "billing";

const BASE_TABS: SettingsTab[] = [
  "profile",
  "api-keys",
  "workspace",
  "members",
];

const LABELS: Record<SettingsTab, string> = {
  profile: "Profile",
  "api-keys": "API keys",
  workspace: "Workspace",
  members: "Members",
  billing: "Billing",
};

function SettingsContent() {
  const { user } = useAuth();
  const { hasBilling } = useEntitlements();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const isAdmin = user?.role === "admin";

  // build the valid-tab list dynamically so gated tabs can't be URL-hacked
  const validTabs: SettingsTab[] = [
    ...BASE_TABS,
    ...(hasBilling ? (["billing"] as const) : []),
  ];

  const tabParam = searchParams.get("tab") as SettingsTab | null;
  const initialTab =
    tabParam && validTabs.includes(tabParam) ? tabParam : "profile";
  const [activeTab, setActiveTab] = useState<SettingsTab>(initialTab);

  // the boards put `Create API key` / `Invite member` in the *page* head
  // rather than the tab body, so the head owns the dialog's open state and the
  // tab renders it
  const [createOpen, setCreateOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);

  const headAction =
    activeTab === "api-keys"
      ? { label: "Create API key", onClick: () => setCreateOpen(true) }
      : activeTab === "members" && isAdmin
        ? { label: "Invite member", onClick: () => setInviteOpen(true) }
        : null;

  useEffect(() => {
    const tab = searchParams.get("tab") as SettingsTab | null;
    if (tab && validTabs.includes(tab)) {
      setActiveTab(tab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // the param is what the tab bar reads on mount, so a selection that does not
  // write it back leaves a refresh landing on a different tab than the one on
  // screen. `replace` rather than `push` — a tab is not a history step.
  function selectTab(tab: SettingsTab) {
    setActiveTab(tab);
    router.replace(`${pathname}?tab=${tab}`, { scroll: false });
  }

  return (
    <div className="flex flex-1 flex-col">
      <PageHead
        className="pb-[18px]"
        title="Settings"
        action={
          headAction ? (
            <button
              type="button"
              onClick={headAction.onClick}
              className="flex h-9 shrink-0 items-center rounded-full bg-accent px-4 text-[14.5px] font-semibold text-bg transition-colors hover:bg-accent/90"
            >
              {headAction.label}
            </button>
          ) : null
        }
      />

      <div className="flex h-[50px] shrink-0 items-center gap-1 border-b border-border-subtle px-7">
        {validTabs.map((tab) => (
          <button
            key={tab}
            type="button"
            aria-pressed={activeTab === tab}
            onClick={() => selectTab(tab)}
            className={tabPillClass(activeTab === tab)}
          >
            {LABELS[tab]}
          </button>
        ))}
      </div>

      {/* every tab renders bare, with no padded wrapper: each one owns bands
          and rows that inset to px-7 themselves, and a wrapper would put them
          at 56 */}
      {activeTab === "profile" && <ProfileTab />}
      {activeTab === "api-keys" && (
        <ApiKeysTab
          createOpen={createOpen}
          onCloseCreate={() => setCreateOpen(false)}
        />
      )}
      {activeTab === "workspace" && <WorkspaceTab />}
      {activeTab === "members" && (
        <MembersTab
          inviteOpen={inviteOpen}
          onCloseInvite={() => setInviteOpen(false)}
        />
      )}
      {activeTab === "billing" && hasBilling && <BillingTab />}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <GuardedRoute
      surface="settings"
      backHref={routes.home}
      backLabel="Back to home"
    >
      <Suspense>
        <SettingsContent />
      </Suspense>
    </GuardedRoute>
  );
}
