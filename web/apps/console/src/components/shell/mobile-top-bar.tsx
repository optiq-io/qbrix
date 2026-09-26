"use client";

import { Menu, Search } from "lucide-react";
import { useCrumbs } from "./breadcrumb";
import { useSidebar } from "./sidebar-context";
import { UserPopover } from "./user-popover";

// there is no room for a trail at 390, so the bar shows the crumb's leaf — the
// same source the desktop topbar uses, rather than a second route table.
function usePageTitle(): string {
  const crumbs = useCrumbs();
  return crumbs[crumbs.length - 1]?.label ?? "qbrix";
}

// board `APP · Home @ 390` / Top bar. below lg the 64px rail cannot survive —
// it becomes this 52px bar and the nav opens as a sheet from the left.
export function MobileTopBar() {
  const { openSheet } = useSidebar();
  const title = usePageTitle();

  return (
    <header className="fixed inset-x-0 top-0 z-40 flex h-[52px] items-center gap-3 border-b border-border-subtle bg-bg-panel px-[14px] lg:hidden">
      <button
        type="button"
        onClick={openSheet}
        aria-label="Open navigation"
        className="flex size-8 shrink-0 items-center justify-center rounded-lg text-text-secondary transition-colors hover:bg-bg-hover"
      >
        <Menu size={21} />
      </button>

      <span className="min-w-0 flex-1 truncate text-[15.5px] font-semibold tracking-[-0.02em] text-text-primary">
        {title}
      </span>

      <button
        type="button"
        onClick={() =>
          window.dispatchEvent(new CustomEvent("qbrix:command-palette:open"))
        }
        aria-label="Open command palette"
        className="flex size-8 shrink-0 items-center justify-center rounded-lg text-text-faint transition-colors hover:bg-bg-hover"
      >
        <Search size={19} />
      </button>

      <UserPopover variant="compact" />
    </header>
  );
}
