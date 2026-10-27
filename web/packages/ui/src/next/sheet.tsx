"use client";

import { useId, useRef } from "react";
import { cn } from "../lib/utils";
import { OverlayPortal, SCRIM, useOverlay } from "./overlay";

type SheetProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  /** the sheet's own action bar; on a phone each action takes an equal share of the width */
  actions?: React.ReactNode;
  dismissable?: boolean;
  children: React.ReactNode;
};

/** rises from the bottom on a phone; at a desk it sits centred like a dialog */
export function Sheet({ open, onClose, title, actions, dismissable = true, children }: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = () => {
    if (dismissable) onClose();
  };
  useOverlay(open, close, panelRef);

  return (
    <OverlayPortal>
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
          <div className={cn("absolute inset-0", SCRIM)} onClick={close} aria-hidden />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            className="relative flex max-h-[90vh] w-full flex-col gap-4 overflow-y-auto rounded-t-[20px] bg-n-surface px-4 pb-[max(28px,env(safe-area-inset-bottom))] pt-3 outline-none sm:w-[440px] sm:rounded-n-panel sm:border sm:border-n-line sm:px-6 sm:pb-6 sm:pt-5 sm:shadow-[0_16px_48px_#0000002e]"
          >
            <div aria-hidden className="flex justify-center sm:hidden">
              <span className="h-1 w-9 rounded-full bg-n-viz-3" />
            </div>
            <h2
              id={titleId}
              className="text-[18px] font-semibold leading-[1.3] text-n-text-1 sm:n-support sm:font-medium"
            >
              {title}
            </h2>
            <div className="n-body flex flex-col gap-4 text-n-text-2">{children}</div>
            {actions && (
              <div className="flex gap-2.5 *:flex-1 sm:justify-end sm:*:flex-none">{actions}</div>
            )}
          </div>
        </div>
      )}
    </OverlayPortal>
  );
}

/** the phone's bottom bar for a page's actions, placed last on the page and edge to edge;
    at a desk the actions sit in the page */
export function ActionBar({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "sticky bottom-0 z-40 flex flex-col gap-2.5 border-t border-n-line bg-n-surface px-4 pb-[max(28px,env(safe-area-inset-bottom))] pt-3 *:w-full",
        "sm:static sm:z-auto sm:flex-row sm:border-0 sm:bg-transparent sm:p-0 sm:*:w-auto",
        className,
      )}
    >
      {children}
    </div>
  );
}
