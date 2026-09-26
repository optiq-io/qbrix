import type { LucideIcon } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";

// board `APP · Transactional states`: "Every full-screen transactional state
// is the same 420px card on $bg... Everywhere else the backdrop is flat." the
// soft tint behind the card belongs to the billing outcomes alone, and it is
// applied by their shell (`components/billing/outcome-shell.tsx`), not here.

export type Tone = "accent" | "positive" | "danger" | "info" | "neutral";

const ICON_TONE: Record<Tone, string> = {
  accent: "bg-accent-soft text-accent",
  positive: "bg-positive/10 text-positive",
  danger: "bg-danger/10 text-danger",
  info: "bg-info-soft text-info",
  neutral: "bg-bg-panel text-text-dim",
};

export function TransactionalCard({
  icon: Icon,
  tone = "accent",
  title,
  body,
  meta,
  children,
}: {
  icon: LucideIcon;
  tone?: Tone;
  title: string;
  body: React.ReactNode;
  /** mono line between the body and the actions, e.g. a workspace url or role */
  meta?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex w-full max-w-[420px] flex-col items-center gap-6 text-center">
      <div
        className={cn(
          "flex size-11 items-center justify-center rounded-[10px]",
          ICON_TONE[tone],
        )}
      >
        <Icon size={19} />
      </div>

      <div className="flex flex-col gap-2.5">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em] text-text-primary">
          {title}
        </h1>
        <p className="text-[14px] leading-[1.6] text-text-dim">{body}</p>
      </div>

      {meta}

      {children && (
        <div className="flex w-full flex-col gap-2.5 pt-1">{children}</div>
      )}
    </div>
  );
}
