"use client";

import { useId, useRef } from "react";
import { X } from "lucide-react";
import { cn } from "../lib/utils";
import { OverlayPortal, PANEL, SCRIM, useOverlay } from "./overlay";

type DialogProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  /** buttons along the bottom, right-aligned */
  footer?: React.ReactNode;
  /** off while a submit is in flight: closing mid-request loses the outcome */
  dismissable?: boolean;
  width?: number;
  children: React.ReactNode;
};

export function Dialog({
  open,
  onClose,
  title,
  footer,
  dismissable = true,
  width = 480,
  children,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = () => {
    if (dismissable) onClose();
  };
  useOverlay(open, close, panelRef);

  return (
    <OverlayPortal>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className={cn("absolute inset-0", SCRIM)} onClick={close} aria-hidden />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            style={{ width }}
            className={cn(
              PANEL,
              "relative flex max-h-[calc(100vh-64px)] max-w-full flex-col overflow-hidden shadow-[0_16px_48px_#0000002e] outline-none",
            )}
          >
            <div className="flex shrink-0 items-start justify-between gap-4 px-6 pt-5">
              <h2 id={titleId} className="n-support font-medium text-n-text-1">
                {title}
              </h2>
              {dismissable && (
                <button
                  type="button"
                  onClick={close}
                  aria-label="Close"
                  className="-mr-1 mt-0.5 rounded-n-chip p-1 text-n-text-3 hover:text-n-text-1"
                >
                  <X size={16} />
                </button>
              )}
            </div>
            <div className="n-body flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 pb-6 pt-3 text-n-text-2">
              {children}
            </div>
            {footer && (
              <div className="flex shrink-0 items-center justify-end gap-2 border-t border-n-line-2 px-6 py-3">
                {footer}
              </div>
            )}
          </div>
        </div>
      )}
    </OverlayPortal>
  );
}
