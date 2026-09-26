import { LayoutGrid, Boxes, Rows3 } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { routes } from "@/config/routes";
import type { GateState } from "@/lib/entitlements";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  // gated on the event_log feature. **shown when locked, hidden when absent**:
  // a scale-gated destination a growth tenant cannot see is a destination they
  // never learn exists, and its UpgradeCard would only ever be reached by
  // typing the URL. an OSS build has no plan to upgrade to, so there it goes.
  ee?: boolean;
};

// board `Console Shell`. there is no Experiments route: home *is* the
// experiments list, which is why the icon is layout-grid and not a flask. and
// no Feature gates route: a gate is per-experiment config with no id of its
// own, so it lives on the experiment's Gate tab.
export const navItems: NavItem[] = [
  { label: "Home", href: routes.home, icon: LayoutGrid },
  { label: "Pools", href: routes.pools, icon: Boxes },
  { label: "Event log", href: routes.eventLog, icon: Rows3, ee: true },
];

export function visibleNavItems(eventsGate: GateState): NavItem[] {
  return navItems.filter((item) => !item.ee || eventsGate !== "absent");
}

export function isNavActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  // home is "/" and would otherwise prefix-match every route
  if (href === "/") return pathname === "/" || pathname.startsWith("/experiments");
  return pathname === href || pathname.startsWith(href + "/");
}
