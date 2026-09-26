"use client";

import { Search } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";

// the palette itself owns ⌘K and this event; both shapes below are just its
// affordance in the shell.
function openPalette() {
  window.dispatchEvent(new CustomEvent("qbrix:command-palette:open"));
}

// board `Console Shell` / Sidebar / Search: h38, r10, $bg-panel on a subtle
// border, 14.5px placeholder and the shortcut in mono.
export function SearchField({ className }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={openPalette}
      aria-label="Open command palette"
      className={cn(
        "flex h-[38px] w-full items-center gap-[10px] rounded-[10px] border border-border-subtle bg-bg-panel px-3 text-left transition-colors hover:border-border",
        className,
      )}
    >
      <Search size={16} className="shrink-0 text-text-faint" />
      <span className="truncate text-[14.5px] text-text-faint">
        Search or jump to…
      </span>
      <span className="ml-auto shrink-0 font-mono text-[12px] tracking-[0.02em] text-text-faint">
        ⌘K
      </span>
    </button>
  );
}

// the same trigger reduced to the rail's 38px slot.
export function SearchRailButton() {
  return (
    <button
      type="button"
      onClick={openPalette}
      aria-label="Open command palette"
      title="Search  ⌘K"
      className="flex size-[38px] items-center justify-center rounded-[10px] text-text-dim transition-colors hover:bg-bg-hover hover:text-text-secondary"
    >
      <Search size={19} />
    </button>
  );
}
