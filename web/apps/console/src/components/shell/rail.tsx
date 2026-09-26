"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PanelLeft, Settings } from "lucide-react";
import { QbrixBrick } from "@qbrix/ui/components/logo";
import { SidebarItem } from "@qbrix/ui/components/sidebar-item";
import { cn } from "@qbrix/ui/lib/utils";
import { useEntitlements } from "@/lib/entitlements";
import { routes } from "@/config/routes";
import { visibleNavItems, isNavActive } from "./nav-items";
import { useSidebar } from "./sidebar-context";
import { SearchRailButton } from "./search-trigger";
import { ServiceHealthDot } from "./service-health";
import { UserPopover } from "./user-popover";

// board `Console Shell` / Rail — 64px, the console's default chrome. it is a
// desktop device: below lg it is replaced by the top bar, and at xl the
// expanded panel takes its place entirely rather than sitting beside it.
export function Rail() {
  const pathname = usePathname();
  const { gate } = useEntitlements();
  const { expanded, toggle } = useSidebar();
  const items = visibleNavItems(gate("event_log"));
  const settingsActive = isNavActive(pathname, routes.settings);

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-40 hidden w-16 flex-col items-center gap-1 border-r border-border-subtle bg-bg py-[14px] lg:flex",
        // at xl the panel replaces the rail; between lg and xl it overlays it
        expanded && "xl:hidden",
      )}
    >
      <Link href={routes.home} aria-label="qbrix home">
        <QbrixBrick size={30} />
      </Link>

      <button
        type="button"
        onClick={toggle}
        aria-label="Expand sidebar"
        title="Expand sidebar  ⌘\"
        // one glyph for both states: the panel itself says which state you are
        // in, so the icon doesn't need to mutate on every click. $text-faint is
        // the "indices, units" tier — too dim for a control, so this sits at
        // $text-dim, level with the nav icons below it.
        className="flex size-9 items-center justify-center rounded-[10px] text-text-dim transition-colors hover:bg-bg-hover hover:text-text-secondary"
      >
        <PanelLeft size={18} />
      </button>

      <span aria-hidden className="h-px w-[26px] bg-border-subtle" />
      <span aria-hidden className="h-[6px]" />

      <SearchRailButton />

      {items.map((item) => (
        <Link key={item.href} href={item.href} aria-label={item.label}>
          <SidebarItem
            icon={item.icon}
            label={item.label}
            collapsed
            active={isNavActive(pathname, item.href)}
          />
        </Link>
      ))}

      <span className="flex-1" />

      <ServiceHealthDot />

      <Link href={routes.settings} aria-label="Settings">
        <SidebarItem
          icon={Settings}
          label="Settings"
          collapsed
          active={settingsActive}
        />
      </Link>

      <UserPopover variant="rail" />
    </aside>
  );
}
