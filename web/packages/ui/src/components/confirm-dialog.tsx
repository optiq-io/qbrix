"use client";

import { AlertTriangle } from "lucide-react";
import { cn } from "../lib/utils";
import { Dialog, DialogButton } from "./dialog";

// the centred, icon-led confirm. it is a `Dialog` with a fixed body rather than
// its own modal: before this it hand-rolled the overlay, and had drifted to a
// different scrim, radius and border from every other dialog in the console.
//
// escape, the scroll lock and the focus trap now come from the shell, which
// this never had — a confirm was the one dialog you could tab straight out of.

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  loading?: boolean;
  /** danger is the default; `accent` is for consequential-but-not-destructive
      confirms like committing an arm, which should not read as a delete */
  tone?: "danger" | "accent";
  /** shown on the confirm button while pending. the default said "Deleting…"
      for every flow, including ones that delete nothing. */
  loadingLabel?: string;
  /** extra controls under the message — e.g. the rollout to resume at */
  children?: React.ReactNode;
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = "Delete",
  loading = false,
  tone = "danger",
  loadingLabel,
  children,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      chrome="bare"
      width={440}
      // closing mid-request abandons an action already in flight
      dismissable={!loading}
      footer={
        // a confirm's actions sit together on the right; the split footer is for
        // a form's Back/Continue, where the two mean opposite directions
        <div className="flex w-full items-center justify-end gap-2.5">
          <DialogButton onClick={onClose} disabled={loading}>
            Cancel
          </DialogButton>
          <DialogButton
            variant="primary"
            onClick={onConfirm}
            disabled={loading}
            className={
              tone === "danger"
                ? "bg-danger text-bg hover:bg-danger/90"
                : undefined
            }
          >
            {loading ? (loadingLabel ?? "Working…") : confirmLabel}
          </DialogButton>
        </div>
      }
    >
      <div className="flex flex-col items-center gap-4">
        <div
          className={cn(
            "flex size-12 items-center justify-center rounded-full",
            tone === "accent" ? "bg-accent/10" : "bg-danger/10",
          )}
        >
          <AlertTriangle
            size={22}
            className={tone === "accent" ? "text-accent" : "text-danger"}
          />
        </div>
        <h2 className="text-center text-[16px] font-semibold tracking-[-0.2px] text-text-primary">
          {title}
        </h2>
        <p className="-mt-2 text-center text-[13px] leading-[1.55] text-text-secondary">
          {message}
        </p>
        {children && <div className="w-full">{children}</div>}
      </div>
    </Dialog>
  );
}
