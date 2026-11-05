"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog } from "@qbrix/ui/next/dialog";
import { workspaceSettingsHome, yourSettingsHome } from "@/components/next/settings/section";
import { openShortcuts, useOpenRequest } from "./command";

const TYPING = "input, textarea, select, [contenteditable='true']";
const SEQUENCE_MS = 1000;

const SHORTCUTS: { keys: string; does: string }[] = [
  { keys: "⌘ K", does: "Search or do" },
  { keys: "G W", does: "Workspace settings" },
  { keys: "G Y", does: "Your settings" },
  { keys: "?", does: "Keyboard shortcuts" },
];

export function ShellKeys() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  useOpenRequest("shortcuts", useCallback(() => setOpen(true), []));

  useEffect(() => {
    let pendingSince = 0;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.target instanceof Element && event.target.closest(TYPING)) return;
      if (event.target instanceof Element && event.target.closest('[role="dialog"], [role="menu"]')) return;

      if (event.key === "?") {
        event.preventDefault();
        openShortcuts();
        return;
      }
      const pending = Date.now() - pendingSince < SEQUENCE_MS;
      pendingSince = 0;
      if (pending && (event.key === "w" || event.key === "y")) {
        event.preventDefault();
        router.push(event.key === "w" ? workspaceSettingsHome : yourSettingsHome);
        return;
      }
      if (event.key === "g" && !event.shiftKey) pendingSince = Date.now();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [router]);

  return (
    <Dialog open={open} onClose={() => setOpen(false)} title="Keyboard shortcuts" width={400}>
      <dl className="flex flex-col gap-2">
        {SHORTCUTS.map((shortcut) => (
          <div key={shortcut.keys} className="flex items-center justify-between">
            <dt className="text-n-text-1">{shortcut.does}</dt>
            <dd className="n-mono text-n-text-3">{shortcut.keys}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
