"use client";

import { useCallback, useEffect, useRef } from "react";
import { X } from "lucide-react";
import { cn } from "../lib/utils";

// the console's one modal shell.
//
// before this there were eight: every dialog hand-rolled its own `fixed
// inset-0` overlay, and they had drifted into three different scrims, two
// radii and two border weights. the chrome here is the one the v3 boards
// actually specify — the same the command palette already uses — so a dialog
// that adopts it stops being a per-file styling decision.
//
// the palette itself is deliberately not built on this: it is a cmdk listbox
// with its own keyboard model, and wrapping it would mean threading half of
// this component's behaviour back out.

const SCRIM = "#050607D9";

type DialogProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  /** the mono line under the title — a wizard's step, or what the thing is */
  eyebrow?: string;
  /** `bare` drops the header row and uses `title` for the accessible name only.
      a confirm is a centred warning, not a titled form, and forcing it into a
      header/body/footer composition would change what it is — the shell is what
      should be shared, not the shape of everything inside it. */
  chrome?: "header" | "bare";
  width?: number;
  /** the row along the bottom. omit for a dialog whose actions sit in its body */
  footer?: React.ReactNode;
  /** off while a submit is in flight: closing mid-request loses the outcome */
  dismissable?: boolean;
  children: React.ReactNode;
};

export function Dialog({
  open,
  onClose,
  title,
  eyebrow,
  chrome = "header",
  width = 620,
  footer,
  dismissable = true,
  children,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => {
    if (dismissable) onClose();
  }, [dismissable, onClose]);

  // escape closes, and tab is kept inside the panel. without the trap, tabbing
  // walks into the page underneath — which is still rendered, just covered.
  useEffect(() => {
    if (!open) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;

      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

  // the page behind must not scroll under the scrim
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // land focus inside on open, so the first Tab continues from the dialog and
  // a screen reader announces it rather than the page it covered
  useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
      <div
        className="absolute inset-0"
        style={{ background: SCRIM }}
        onClick={close}
        aria-hidden
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        style={{ width, boxShadow: "0 24px 64px #00000066" }}
        className="relative z-10 flex max-h-[calc(100vh-96px)] max-w-full flex-col overflow-hidden rounded-[14px] border border-border bg-bg-overlay outline-none"
      >
        {chrome === "header" && (
        <div className="flex shrink-0 flex-col gap-[5px] border-b border-border-subtle px-[26px] pb-[18px] pt-[22px]">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-[17px] font-semibold text-text-primary">
              {title}
            </h2>
            <button
              type="button"
              onClick={close}
              aria-label="Close"
              className="shrink-0 text-text-dim transition-colors hover:text-text-primary disabled:opacity-40"
              disabled={!dismissable}
            >
              <X size={17} />
            </button>
          </div>
          {eyebrow && (
            <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-text-faint">
              {eyebrow}
            </span>
          )}
        </div>
        )}

        <div
          className={cn(
            "flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-[26px] pb-[26px]",
            chrome === "header" ? "pt-6" : "pt-[26px]",
          )}
        >
          {children}
        </div>

        {footer && (
          <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border-subtle px-[26px] py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/** the dialog footer's own button shapes — r9, smaller than the page pills in
 *  `button.tsx`, which is what the boards draw inside a dialog. */
export function DialogButton({
  variant = "ghost",
  className,
  type = "button",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost";
}) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-[9px] px-4 py-[9px] text-[13.5px] transition-colors disabled:pointer-events-none disabled:opacity-50",
        variant === "primary"
          ? "bg-accent font-semibold text-bg hover:bg-accent/90"
          : "border border-border font-medium text-text-secondary hover:border-border-strong hover:text-text-primary",
        className,
      )}
      {...props}
    />
  );
}
