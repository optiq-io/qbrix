import { Activity, History, Inbox, Repeat, Target } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { routes } from "@/config/routes";

export type NextNavItem = { label: string; href: string; icon: LucideIcon };

export const nextNav: NextNavItem[] = [
  { label: "Inbox", href: routes.next.inbox, icon: Inbox },
  { label: "Loops", href: routes.next.home, icon: Repeat },
  { label: "Metrics", href: routes.next.metrics, icon: Target },
  { label: "Event log", href: routes.next.eventLog, icon: Activity },
  { label: "Changes", href: routes.next.changes, icon: History },
];

export function isNextNavActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === routes.next.home) {
    return pathname === href || pathname.startsWith(`${href}/loops/`);
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

// the inbox, a change and a loop link work on a phone; everything else asks
// for a larger screen ("Desktop first")
export function phoneAllowed(pathname: string | null): boolean {
  if (!pathname) return false;
  const { inbox, changes } = routes.next;
  if (pathname === inbox || pathname.startsWith(`${inbox}/`)) return true;
  if (pathname.startsWith(`${changes}/`)) return true;
  return pathname.startsWith(`${routes.next.home}/loops/`);
}
