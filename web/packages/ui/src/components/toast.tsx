"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
} from "react";
import { X, CheckCircle2, AlertCircle, Info, ArrowRight } from "lucide-react";
import { cn } from "../lib/utils";

type ToastType = "success" | "error" | "info";

export type ToastAction = {
  label: string;
  href?: string;
  onClick?: () => void;
};

export type RichToast = {
  type?: ToastType;
  title?: string;
  message: string;
  hint?: string;
  action?: ToastAction;
  durationMs?: number;
};

interface Toast extends RichToast {
  id: string;
  type: ToastType;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  errorRich: (payload: Omit<RichToast, "type">) => void;
  show: (payload: RichToast) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

let toastId = 0;

const DEFAULT_DURATION_MS: Record<ToastType, number> = {
  success: 4000,
  info: 4000,
  error: 8000,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback((payload: RichToast) => {
    const id = String(++toastId);
    const type = payload.type ?? "info";
    setToasts((prev) => [...prev, { ...payload, id, type }]);
  }, []);

  const addToast = useCallback(
    (message: string, type: ToastType = "info") => {
      show({ message, type });
    },
    [show],
  );

  const value: ToastContextValue = {
    toast: addToast,
    success: useCallback((msg: string) => addToast(msg, "success"), [addToast]),
    error: useCallback((msg: string) => addToast(msg, "error"), [addToast]),
    info: useCallback((msg: string) => addToast(msg, "info"), [addToast]),
    errorRich: useCallback(
      (payload: Omit<RichToast, "type">) => show({ ...payload, type: "error" }),
      [show],
    ),
    show,
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex w-[min(90vw,400px)] flex-col-reverse gap-2">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => removeToast(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    const duration = toast.durationMs ?? DEFAULT_DURATION_MS[toast.type];
    timerRef.current = setTimeout(onDismiss, duration);
    return () => clearTimeout(timerRef.current);
  }, [onDismiss, toast.durationMs, toast.type]);

  const Icon =
    toast.type === "success"
      ? CheckCircle2
      : toast.type === "error"
        ? AlertCircle
        : Info;

  const rich = Boolean(toast.title || toast.hint || toast.action);

  return (
    <div
      role={toast.type === "error" ? "alert" : "status"}
      className={cn(
        "flex gap-3 rounded-lg border px-4 py-3 shadow-lg animate-in slide-in-from-right-full duration-200",
        toast.type === "success" && "border-positive/30 bg-positive/10 text-positive",
        toast.type === "error" && "border-danger/30 bg-danger/10 text-danger",
        toast.type === "info" && "border-border bg-bg-panel text-text-secondary",
        rich ? "items-start" : "items-center",
      )}
    >
      <Icon size={16} className={cn("shrink-0", rich && "mt-0.5")} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {toast.title ? (
          <div className="flex flex-col gap-0.5">
            <span className="text-[13px] font-semibold leading-tight">{toast.title}</span>
            <span className="text-[12px] font-medium leading-snug opacity-90">
              {toast.message}
            </span>
          </div>
        ) : (
          <span className="text-[13px] font-medium leading-snug break-words">
            {toast.message}
          </span>
        )}
        {toast.hint && (
          <span className="text-[11px] leading-snug opacity-75">{toast.hint}</span>
        )}
        {toast.action && <ToastActionButton action={toast.action} onDismiss={onDismiss} />}
      </div>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 opacity-60 transition-opacity hover:opacity-100"
      >
        <X size={14} />
      </button>
    </div>
  );
}

function ToastActionButton({
  action,
  onDismiss,
}: {
  action: ToastAction;
  onDismiss: () => void;
}) {
  const className =
    "mt-1 inline-flex items-center gap-1 self-start rounded border border-current/30 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide transition-opacity hover:opacity-80";

  if (action.href) {
    return (
      <a href={action.href} onClick={onDismiss} className={className}>
        {action.label}
        <ArrowRight size={11} />
      </a>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        action.onClick?.();
        onDismiss();
      }}
      className={className}
    >
      {action.label}
      <ArrowRight size={11} />
    </button>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (context === undefined) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}
