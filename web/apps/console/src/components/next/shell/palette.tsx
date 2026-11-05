"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import { LogOut, Plus, Search, Settings, UserCog } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { OverlayPortal, PANEL, SCRIM, useOverlay } from "@qbrix/ui/next/overlay";
import { cn } from "@qbrix/ui/lib/utils";
import { routes } from "@/config/routes";
import { useAuth } from "@/lib/auth/context";
import { workspaceSettingsHome, yourSettingsHome } from "@/components/next/settings/section";
import { useOpenRequest } from "./command";
import { nextNav } from "./nav";

type Entry = { id: string; label: string; icon: LucideIcon; hint?: string; run: () => void };

export function Palette() {
  const router = useRouter();
  const { logout } = useAuth();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useOverlay(open, close, panelRef);
  useOpenRequest("palette", useCallback(() => setOpen(true), []));

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const go = (href: string) => () => router.push(href);
  const groups: { heading: string; entries: Entry[] }[] = [
    {
      heading: "Go to",
      entries: [
        ...nextNav.map((item) => ({ id: item.href, label: item.label, icon: item.icon, run: go(item.href) })),
        { id: "workspace-settings", label: "Workspace settings", icon: Settings, hint: "G W", run: go(workspaceSettingsHome) },
        { id: "your-settings", label: "Your settings", icon: UserCog, hint: "G Y", run: go(yourSettingsHome) },
      ],
    },
    {
      heading: "Do",
      entries: [
        { id: "new-loop", label: "New loop", icon: Plus, run: go(routes.next.newLoop) },
        {
          id: "sign-out",
          label: "Sign out",
          icon: LogOut,
          run: async () => {
            await logout();
            window.location.assign(routes.login);
          },
        },
      ],
    },
  ];

  return (
    <OverlayPortal>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[14vh]">
          <div className={cn("absolute inset-0", SCRIM)} onClick={close} aria-hidden />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Search or do"
            className={cn(PANEL, "relative w-[560px] max-w-full overflow-hidden shadow-[0_16px_48px_#0000002e]")}
          >
            <Command label="Search or do" loop>
              <div className="flex items-center gap-2 border-b border-n-line-2 px-4">
                <Search size={15} className="shrink-0 text-n-text-3" />
                <Command.Input
                  autoFocus
                  placeholder="Search or do"
                  className="h-11 flex-1 bg-transparent n-body text-n-text-1 outline-none placeholder:text-n-text-3"
                />
              </div>
              <Command.List className="max-h-[360px] overflow-y-auto p-1.5">
                <Command.Empty className="px-2.5 py-3 n-body text-n-text-3">Nothing matches.</Command.Empty>
                {groups.map((group) => (
                  <Command.Group
                    key={group.heading}
                    heading={group.heading}
                    className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:n-label [&_[cmdk-group-heading]]:text-n-text-3"
                  >
                    {group.entries.map((entry) => (
                      <Command.Item
                        key={entry.id}
                        value={entry.label}
                        onSelect={() => {
                          close();
                          entry.run();
                        }}
                        className="flex cursor-pointer items-center gap-2.5 rounded-n-chip px-2.5 py-1.5 n-body text-n-text-1 aria-selected:bg-n-fill-2"
                      >
                        <entry.icon size={15} className="shrink-0 text-n-text-2" />
                        <span className="flex-1">{entry.label}</span>
                        {entry.hint && <span className="n-mono text-[11px] text-n-text-3">{entry.hint}</span>}
                      </Command.Item>
                    ))}
                  </Command.Group>
                ))}
              </Command.List>
            </Command>
          </div>
        </div>
      )}
    </OverlayPortal>
  );
}
