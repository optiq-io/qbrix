"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { Settings, LogOut, Ellipsis } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { useAuth } from "@/lib/auth/context";
import { routes } from "@/config/routes";
import { PlanLine } from "@/lib/edition";

function initialsOf(email?: string, name?: string): string {
  const source = name?.trim() || email;
  if (!source) return "??";
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

// board `Console Shell`: the avatar is a $viz-2 disc with the initials knocked
// out in $bg. viz-2 is identity colour, not status — it carries no meaning
// beyond "this is you", which is why it sits outside the semantic set.
export function UserAvatar({ size = 28 }: { size?: number }) {
  const { user } = useAuth();
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full border border-border bg-viz-2 font-mono text-[11px] tracking-[0.02em] text-bg"
      style={{ width: size, height: size }}
    >
      {initialsOf(user?.email, user?.name)}
    </span>
  );
}

type Variant = "rail" | "row" | "compact";

export function UserPopover({ variant = "row" }: { variant?: Variant }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const displayName = user?.name ?? user?.email?.split("@")[0] ?? "User";

  return (
    <div ref={ref} className={cn("relative", variant === "row" && "w-full")}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="User menu"
        className={cn(
          "flex items-center transition-colors",
          variant === "row" &&
            "h-11 w-full gap-[11px] rounded-[10px] px-[10px] hover:bg-bg-hover",
          variant === "rail" && "size-[38px] justify-center rounded-[10px]",
          variant === "compact" && "shrink-0",
        )}
      >
        <UserAvatar size={variant === "compact" ? 27 : 28} />
        {variant === "row" && (
          <>
            <span className="flex min-w-0 flex-1 flex-col items-start gap-px text-left">
              <span className="w-full truncate text-[14.5px] text-text-secondary">
                {displayName}
              </span>
              <PlanLine />
            </span>
            <Ellipsis size={15} className="shrink-0 text-text-faint" />
          </>
        )}
      </button>
      {open ? (
        <div
          className={cn(
            "absolute z-50 w-56 rounded-md border border-border-subtle bg-bg-overlay py-1 shadow-2xl",
            variant === "compact"
              ? "right-0 top-full mt-2"
              : "bottom-full left-0 mb-2",
          )}
        >
          <div className="border-b border-border-subtle px-3 py-2">
            <div className="truncate text-[12px] font-semibold text-text-primary">
              {displayName}
            </div>
            <div className="truncate font-mono text-[10px] text-text-dim">
              {user?.email}
            </div>
          </div>
          <Link
            href={routes.settings}
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-[12px] text-text-secondary transition-colors hover:bg-bg-panel hover:text-text-primary"
          >
            <Settings size={13} className="text-text-dim" />
            Settings
          </Link>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              logout();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-text-secondary transition-colors hover:bg-bg-panel hover:text-text-primary"
          >
            <LogOut size={13} className="text-text-dim" />
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
