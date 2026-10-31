"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronsUpDown, Search } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { useWorkspaceName } from "@/components/shell/workspace-row";
import { isNextNavActive, nextNav } from "./nav";
import { PinnedSection } from "./pinned";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 hidden w-[232px] flex-col gap-0.5 border-r border-n-line-2 bg-n-bg px-2 py-3 lg:flex">
      <WorkspaceRow />

      <span className="h-3 shrink-0" />
      <SearchField />
      <span className="h-3.5 shrink-0" />

      <nav className="flex flex-col gap-0.5">
        {nextNav.map((item) => {
          const active = isNextNavActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-n-control px-2 py-1 n-body text-n-text-2 hover:bg-n-fill-1",
                active && "bg-n-fill-2 font-medium text-n-text-1 hover:bg-n-fill-2",
              )}
            >
              <item.icon size={15} className="shrink-0 text-n-text-2" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <span className="h-[18px] shrink-0" />
      <PinnedSection />

      <span className="flex-1" />
      <YouRow />
    </aside>
  );
}

function WorkspaceRow() {
  const name = useWorkspaceName();

  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <span className="flex size-[22px] shrink-0 items-center justify-center rounded-n-control bg-n-ink text-[12px] font-semibold text-n-on-ink">
        {name?.charAt(0).toLowerCase()}
      </span>
      <span className="min-w-0 flex-1 truncate n-body font-semibold text-n-text-1">{name}</span>
      <ChevronsUpDown size={15} className="shrink-0 text-n-text-3" />
    </div>
  );
}

function SearchField() {
  return (
    <button
      type="button"
      className="flex items-center gap-2 rounded-n-control border border-n-line px-2 py-1.5 text-left text-n-text-3"
    >
      <Search size={14} className="shrink-0" />
      <span className="flex-1 n-body">Search or do</span>
      <span className="n-label font-normal">⌘K</span>
    </button>
  );
}

function YouRow() {
  const { user } = useAuth();
  const name = user?.name || user?.email.split("@")[0] || "";

  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <span className="flex size-[22px] shrink-0 items-center justify-center rounded-full bg-n-fill-2 text-[11px] font-semibold text-n-text-2">
        {name.charAt(0).toUpperCase()}
      </span>
      <span className="min-w-0 flex-1 truncate n-body text-n-text-2">{name}</span>
      <span data-slot="connections" />
    </div>
  );
}
