"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { openPalette } from "./command";
import { isNextNavActive, nextNav } from "./nav";
import { PinnedSection } from "./pinned";
import { WorkspaceMenu } from "./workspace-menu";
import { YourMenu } from "./your-menu";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 hidden w-[232px] flex-col gap-0.5 border-r border-n-line-2 bg-n-bg px-2 py-3 lg:flex">
      <WorkspaceMenu />

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
      <YourMenu />
    </aside>
  );
}

function SearchField() {
  return (
    <button
      type="button"
      onClick={openPalette}
      className="flex items-center gap-2 rounded-n-control border border-n-line px-2 py-1.5 text-left text-n-text-3"
    >
      <Search size={14} className="shrink-0" />
      <span className="flex-1 n-body">Search or do</span>
      <span className="n-label font-normal">⌘K</span>
    </button>
  );
}
