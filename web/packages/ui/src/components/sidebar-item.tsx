import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";

// board `01 · Components` / Sidebar item. the active state is a neutral
// $bg-hover ground plus brighter icon and label at weight 500 — no accent tint
// and no indicator rail. the ground is what separates it from hover; the accent
// stays available for the one thing on the screen that earns it.

type SidebarItemProps = {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  /** collapsed rail: the label is dropped and the item squares off */
  collapsed?: boolean;
  className?: string;
};

export function SidebarItem({
  icon: Icon,
  label,
  active = false,
  collapsed = false,
  className,
}: SidebarItemProps) {
  return (
    <span
      className={cn(
        "flex h-[38px] items-center gap-3 transition-colors",
        // the rail draws its slots one pixel rounder than the panel's
        collapsed ? "w-[38px] justify-center rounded-[10px]" : "rounded-[9px] px-[11px]",
        active ? "bg-bg-hover" : "hover:bg-bg-hover",
        className,
      )}
      title={collapsed ? label : undefined}
    >
      <Icon
        size={18}
        className={cn("shrink-0", active ? "text-text-primary" : "text-text-dim")}
      />
      {!collapsed && (
        <span
          className={cn(
            "truncate text-[15px]",
            active
              ? "font-medium text-text-primary"
              : "text-text-secondary",
          )}
        >
          {label}
        </span>
      )}
    </span>
  );
}
