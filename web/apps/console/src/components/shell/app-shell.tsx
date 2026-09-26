"use client";

import { cn } from "@qbrix/ui/lib/utils";
import { CommandPalette } from "@/components/command-palette";
import { SidebarProvider, useSidebar } from "./sidebar-context";
import { PinnedProvider } from "./pinned";
import { Rail } from "./rail";
import { SidebarPanel } from "./sidebar-panel";
import { MobileTopBar } from "./mobile-top-bar";
import { Topbar } from "./topbar";

// board `03 · Responsive System` / G — the console's chrome has three widths:
//
//   ≥ xl     rail collapsed by default; expanding replaces it with the 292
//            panel and pushes the content across
//   lg – xl  rail is locked; the panel overlays it rather than pushing
//   < lg     rail becomes a 52px top bar, nav opens as a sheet from the left
//
// every element is fixed-position, so the page keeps document scroll exactly as
// it did under the bottom bar and each page's sticky headers keep working.
function Chrome({ children }: { children: React.ReactNode }) {
  const { expanded, collapse, sheetOpen, closeSheet } = useSidebar();

  return (
    <>
      <MobileTopBar />
      <Rail />

      {/* between lg and xl the panel floats over the content, so it needs a
          scrim to dismiss; at xl it is in the layout and must not. */}
      <button
        type="button"
        aria-label="Collapse sidebar"
        onClick={collapse}
        inert={!expanded}
        className={cn(
          "fixed inset-0 z-40 hidden bg-black/50 transition-opacity lg:block xl:hidden",
          expanded
            ? "opacity-100 duration-[var(--motion-move)] ease-entrance"
            : "pointer-events-none opacity-0 duration-[var(--motion-exit)] ease-exit",
        )}
      />
      <SidebarPanel
        onCollapse={collapse}
        inert={!expanded}
        className={cn(
          "fixed inset-y-0 left-0 z-50 hidden transition-transform lg:flex",
          // at xl the panel pushes the content, and animating that reflows
          // every row and chart for the duration — so xl is instant. lg and
          // below it overlays, which is a pure composited transform.
          "xl:transition-none",
          expanded
            ? "translate-x-0 duration-[var(--motion-move)] ease-entrance"
            : "-translate-x-full duration-[var(--motion-exit)] ease-exit",
        )}
      />

      <button
        type="button"
        aria-label="Close navigation"
        onClick={closeSheet}
        inert={!sheetOpen}
        className={cn(
          "fixed inset-0 z-40 bg-black/50 transition-opacity lg:hidden",
          sheetOpen
            ? "opacity-100 duration-[var(--motion-move)] ease-entrance"
            : "pointer-events-none opacity-0 duration-[var(--motion-exit)] ease-exit",
        )}
      />
      <SidebarPanel
        onCollapse={closeSheet}
        collapseLabel="Close navigation"
        inert={!sheetOpen}
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex transition-transform lg:hidden",
          sheetOpen
            ? "translate-x-0 duration-[var(--motion-move)] ease-entrance"
            : "-translate-x-full duration-[var(--motion-exit)] ease-exit",
        )}
      />

      <main
        className={cn(
          // the top bar comes off the viewport below lg, so min-height has to
          // account for it or every short page grows a scrollbar
          "flex min-h-[calc(100vh-52px)] flex-col bg-bg pt-[52px] lg:min-h-screen lg:pl-16 lg:pt-0",
          expanded && "xl:pl-[292px]",
        )}
      >
        <Topbar />
        {children}
      </main>

      {/* the palette overlays any page, so it stays outside the chrome */}
      <CommandPalette />
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <PinnedProvider>
        <Chrome>{children}</Chrome>
      </PinnedProvider>
    </SidebarProvider>
  );
}
