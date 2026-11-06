"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { PANEL } from "@qbrix/ui/next/overlay";
import { usePopover } from "@qbrix/ui/next/popover";
import { cn } from "@qbrix/ui/lib/utils";

export function EndMenu({
  label,
  opens,
  width,
  trigger,
  children,
}: {
  label: string;
  /** over: the panel covers its trigger, so its head takes the row's place */
  opens: "over" | "up";
  width: number;
  trigger: React.ReactNode;
  children: (close: () => void) => React.ReactNode;
}) {
  const { open, setOpen, close, wrapperRef, triggerRef, contentRef, onContentKeyDown, onTriggerKeyDown } =
    usePopover("menuitem");

  return (
    <div ref={wrapperRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
        className={cn(
          "flex w-full items-center gap-2 rounded-n-control px-2 py-1 text-left outline-none hover:bg-n-fill-1 focus-visible:bg-n-fill-1",
          open && "bg-n-fill-1",
        )}
      >
        {trigger}
      </button>

      {open && (
        <div
          ref={contentRef}
          role="menu"
          aria-label={label}
          onKeyDown={onContentKeyDown}
          style={{ width }}
          className={cn(
            PANEL,
            "absolute z-40 flex flex-col p-1.5 shadow-[0_8px_24px_#0000001f]",
            opens === "over" ? "-top-1.5 -left-1.5" : "bottom-[calc(100%+4px)] left-0",
          )}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}

type RowAction =
  | { href: string; external?: boolean; onSelect?: never }
  | { onSelect: () => void; href?: never; external?: never };

const ROW =
  "flex w-full items-center gap-2.5 rounded-n-chip px-2 py-1.5 text-left n-body text-n-text-1 outline-none hover:bg-n-fill-1 focus:bg-n-fill-2";

export function MenuRow({
  icon: Icon,
  label,
  hint,
  mono,
  close,
  ...action
}: {
  icon: LucideIcon;
  label: string;
  hint?: React.ReactNode;
  mono?: boolean;
  close: () => void;
} & RowAction) {
  const body = (
    <>
      <Icon size={15} className="shrink-0 text-n-text-2" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {hint !== undefined && (
        <span className={cn("shrink-0 text-n-text-3", mono ? "n-mono text-[11px]" : "n-label font-normal")}>
          {hint}
        </span>
      )}
    </>
  );

  if (action.href !== undefined) {
    return (
      <Link
        href={action.href}
        role="menuitem"
        tabIndex={-1}
        target={action.external ? "_blank" : undefined}
        rel={action.external ? "noreferrer" : undefined}
        onClick={close}
        className={ROW}
      >
        {body}
      </Link>
    );
  }
  return (
    <button
      type="button"
      role="menuitem"
      tabIndex={-1}
      onClick={() => {
        close();
        action.onSelect();
      }}
      className={ROW}
    >
      {body}
    </button>
  );
}

export function MenuDivider() {
  return <div role="separator" className="my-1 h-px shrink-0 bg-n-line-2" />;
}
