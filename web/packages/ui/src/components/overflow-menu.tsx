"use client";

import { useEffect, useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import { cn } from "../lib/utils";

// the console keeps ending up with actions the boards do not draw but that have
// no other route — Reset/Delete on the experiment header, Rename/Delete on a
// pool row. this is that affordance, shared, so the behaviour is identical in
// both places and there is not a third hand-rolled variant next time.
//
// closing is click-outside + Escape rather than onBlur: blur fires as focus
// moves *into* the menu, so a keyboard user tabbing to an item would close it
// before reaching one.

export type OverflowItem = {
  label: string;
  onSelect: () => void;
  tone?: "default" | "danger";
  disabled?: boolean;
  title?: string;
};

export function OverflowMenu({
  items,
  label = "More actions",
  align = "right",
  hideUntilHover = false,
  className,
}: {
  items: OverflowItem[];
  label?: string;
  align?: "left" | "right";
  /** row-level menus stay invisible until the row is hovered or focused */
  hideUntilHover?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className={cn("relative shrink-0", className)}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center justify-center rounded-[7px] text-text-dim transition-colors hover:bg-bg-hover hover:text-text-primary",
          hideUntilHover
            ? "size-8"
            : "size-9 rounded-full bg-bg-hover hover:bg-white/[0.09]",
          hideUntilHover &&
            !open &&
            "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
        )}
      >
        <MoreHorizontal size={16} />
      </button>

      {open && (
        <div
          role="menu"
          className={cn(
            "absolute top-[calc(100%+6px)] z-30 w-44 overflow-hidden rounded-[10px] border border-border-subtle bg-bg-panel py-1 shadow-lg",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              title={item.title}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={cn(
                "flex w-full items-center px-3 py-2 text-left text-[13.5px] transition-colors disabled:pointer-events-none disabled:opacity-40",
                item.tone === "danger"
                  ? "text-danger hover:bg-danger/10"
                  : "text-text-secondary hover:bg-bg-hover hover:text-text-primary",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
