"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Settings } from "lucide-react";
import { SidebarItem } from "@qbrix/ui/components/sidebar-item";
import { cn } from "@qbrix/ui/lib/utils";
import { useEntitlements } from "@/lib/entitlements";
import { routes } from "@/config/routes";
import { visibleNavItems, isNavActive } from "./nav-items";
import { useExperimentId } from "./breadcrumb";
import { PinnedSection } from "./pinned";
import { SearchField } from "./search-trigger";
import { ServiceHealthCard } from "./service-health";
import { UserPopover } from "./user-popover";
import { WorkspaceRow } from "./workspace-row";

// board `Console Shell` / Sidebar (292) — one panel, three placements: in flow
// at xl, overlaying the rail between lg and xl, and as the left sheet below lg.
export function SidebarPanel({
  onCollapse,
  collapseLabel,
  inert,
  className,
}: {
  onCollapse: () => void;
  collapseLabel?: string;
  /** closed: keeps it mounted so it can transition, but out of tab order and
      out of the accessibility tree */
  inert?: boolean;
  className?: string;
}) {
  const pathname = usePathname();
  const { gate } = useEntitlements();
  const items = visibleNavItems(gate("event_log"));
  const experimentId = useExperimentId();

  return (
    <aside
      inert={inert}
      className={cn(
        "flex w-[292px] flex-col gap-[18px] border-r border-border-subtle bg-bg-raised px-[14px] py-4",
        className,
      )}
    >
      <WorkspaceRow onCollapse={onCollapse} collapseLabel={collapseLabel} />

      <SearchField />

      <nav className="flex flex-col gap-[2px]">
        {items.map((item) => (
          <Link key={item.href} href={item.href}>
            <SidebarItem
              icon={item.icon}
              label={item.label}
              active={isNavActive(pathname, item.href)}
            />
          </Link>
        ))}
      </nav>

      <PinnedSection currentId={experimentId ?? undefined} />

      <span className="flex-1" />

      <Link href={routes.settings}>
        <SidebarItem
          icon={Settings}
          label="Settings"
          active={isNavActive(pathname, routes.settings)}
        />
      </Link>

      <ServiceHealthCard />

      <UserPopover variant="row" />
    </aside>
  );
}
