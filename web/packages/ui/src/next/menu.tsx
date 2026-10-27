"use client";

import { MoreHorizontal } from "lucide-react";
import { cn } from "../lib/utils";
import { IconButton } from "./button";
import { PANEL } from "./overlay";
import { usePopover } from "./popover";

export type MenuItem = {
  label: string;
  /** what choosing it does, on a second line: "Its history stays" */
  consequence?: string;
  onSelect: () => void;
  tone?: "default" | "danger";
  /** false leaves the item out for a person who can't make this change */
  canEdit?: boolean;
};

export function Menu({
  items,
  label = "More actions",
  align = "right",
  className,
}: {
  items: MenuItem[];
  label?: string;
  align?: "left" | "right";
  className?: string;
}) {
  const { open, setOpen, close, wrapperRef, triggerRef, contentRef, onContentKeyDown, onTriggerKeyDown } =
    usePopover("menuitem");
  const shown = items.filter((item) => item.canEdit !== false);
  if (shown.length === 0) return null;

  return (
    <div ref={wrapperRef} className={cn("relative inline-flex shrink-0", className)}>
      <IconButton
        ref={triggerRef}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
      >
        <MoreHorizontal size={16} />
      </IconButton>

      {open && (
        <div
          ref={contentRef}
          role="menu"
          aria-label={label}
          onKeyDown={onContentKeyDown}
          className={cn(
            PANEL,
            "absolute top-[calc(100%+4px)] z-30 flex min-w-48 flex-col p-1 shadow-[0_8px_24px_#0000001f]",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {shown.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                close();
                item.onSelect();
              }}
              className="flex flex-col items-start rounded-n-chip px-2.5 py-1.5 text-left outline-none hover:bg-n-fill-1 focus:bg-n-fill-1"
            >
              <span
                className={cn(
                  "n-body",
                  item.tone === "danger" ? "text-n-no-fg" : "text-n-text-1",
                )}
              >
                {item.label}
              </span>
              {item.consequence && (
                <span className="n-meta text-n-text-3">{item.consequence}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
