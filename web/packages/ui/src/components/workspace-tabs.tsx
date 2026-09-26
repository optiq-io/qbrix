"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "../lib/utils";

export type WorkspaceTabItem = {
  label: string;
  href: string;
  ee?: boolean;
  exact?: boolean;
};

type WorkspaceTabsProps = {
  items: WorkspaceTabItem[];
  className?: string;
};

function isTabActive(pathname: string | null, href: string, exact?: boolean): boolean {
  if (!pathname) return false;
  if (pathname === href) return true;
  if (exact) return false;
  return pathname.startsWith(href + "/");
}

// board `APP · Experiment / Overview` / Tabs and `APP · Settings / API Keys` /
// Tabs: h36, r10, 14px inset, 15px label, and **no icons** — both bars follow
// the boards that draw them rather than the smaller r6/13px `Tab` published on
// `01 · Components`. that divergence is real and recorded on the ticket.
//
// exported because settings selects a tab by state rather than by route, so it
// cannot use `WorkspaceTabs` itself — but it must not fork the pill.
export function tabPillClass(active: boolean): string {
  return cn(
    "flex h-9 shrink-0 items-center rounded-[10px] px-3.5 text-[15px] transition-colors",
    active
      ? "bg-white/[0.07] font-medium text-text-primary"
      : "text-text-dim hover:bg-bg-hover hover:text-text-secondary",
  );
}

export function WorkspaceTabs({ items, className }: WorkspaceTabsProps) {
  const pathname = usePathname();

  return (
    <div className={cn("flex items-center gap-1", className)}>
      {items.map((item) => {
        const active = isTabActive(pathname, item.href, item.exact);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={tabPillClass(active)}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}
