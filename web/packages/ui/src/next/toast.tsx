"use client";

import { useCallback, useContext, useEffect } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { ToastOutletContext, useToastTimer, type ToastEntry } from "../components/toast";
import { cn } from "../lib/utils";
import { Button, buttonClass } from "./button";
import { PANEL } from "./overlay";

const ICON = {
  success: [CheckCircle2, "text-n-ok-fg"],
  error: [AlertCircle, "text-n-no-fg"],
  info: [Info, "text-n-text-3"],
} as const;

/** renders useToast()'s toasts inside the next scope, in place of the v3 stack,
    for as long as it's mounted */
export function Toaster() {
  const outlet = useContext(ToastOutletContext);
  const claim = outlet?.claim;

  useEffect(() => claim?.(), [claim]);

  if (!outlet) return null;

  return (
    <div className="fixed inset-x-4 bottom-4 z-[100] flex flex-col-reverse gap-2 sm:left-auto sm:w-[360px]">
      {outlet.toasts.map((t) => (
        <ToastItem key={t.id} toast={t} dismiss={outlet.dismiss} />
      ))}
    </div>
  );
}

function ToastItem({ toast, dismiss }: { toast: ToastEntry; dismiss: (id: string) => void }) {
  const onDismiss = useCallback(() => dismiss(toast.id), [dismiss, toast.id]);
  useToastTimer(toast, onDismiss);
  const [Icon, tone] = ICON[toast.type];
  const action = toast.action;

  return (
    <div
      role={toast.type === "error" ? "alert" : "status"}
      className={cn(PANEL, "flex items-start gap-2.5 p-3 shadow-[0_8px_24px_#0000001f]")}
    >
      <Icon size={15} className={cn("mt-0.5 shrink-0", tone)} />
      <div className="n-body flex min-w-0 flex-1 flex-col gap-0.5">
        {toast.title && <span className="font-medium text-n-text-1">{toast.title}</span>}
        <span className={cn("break-words", toast.title ? "text-n-text-2" : "text-n-text-1")}>
          {toast.message}
        </span>
        {toast.hint && <span className="n-meta text-n-text-3">{toast.hint}</span>}
        {action &&
          (action.href ? (
            <a href={action.href} onClick={onDismiss} className={buttonClass("secondary", "sm", "mt-1.5 self-start")}>
              {action.label}
            </a>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              className="mt-1.5 self-start"
              onClick={() => {
                action.onClick?.();
                onDismiss();
              }}
            >
              {action.label}
            </Button>
          ))}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 rounded-n-chip p-0.5 text-n-text-3 hover:text-n-text-1"
      >
        <X size={14} />
      </button>
    </div>
  );
}
