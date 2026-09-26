import type { ReactNode } from "react";
import { ArrowUpRight, Plus } from "lucide-react";
import { cn } from "../lib/utils";
import { StateActions } from "./state-actions";

// board `APP · Empty, loading & error states`, rows POOLS / GATES / EVENT LOG.
//
// the board draws each of these inside a `$bg-raised` panel with its own head
// row. those are pre-rule and deliberately dropped: the
// `APP · Pools` board puts its column bar and rows directly on the page ground,
// like Home and the experiment tabs, so the empty state does too.
//
// the action pair is `StateActions`, not a local copy — it is pixel-identical
// across all six states on this board and the gated card uses it too. it is deliberately *not* `Button / Primary` (h36 r18 pill,
// 14.5/600); this compact shape belongs to full-page states.

type PrimaryAction = {
  label: string;
  /** one of the two, not both. creation moved to real routes, so an empty
      state's primary action is now usually a link rather than a handler. */
  onClick?: () => void;
  href?: string;
  /** "create" draws the leading plus; "neutral" is bare (e.g. "Try again") */
  shape?: "create" | "neutral";
};

type SecondaryAction = {
  label: string;
  href: string;
  external?: boolean;
};

type EmptyStateProps = {
  icon: ReactNode;
  title: string;
  description: string;
  primaryAction?: PrimaryAction;
  secondaryAction?: SecondaryAction;
  className?: string;
};

export function EmptyState({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-[26px] py-20",
        className,
      )}
    >
      <div className="opacity-95">{icon}</div>

      <h3 className="pt-5 text-center text-[15.5px] font-semibold leading-tight tracking-[-0.2px] text-text-primary">
        {title}
      </h3>
      <p className="max-w-[404px] pt-[9px] text-center text-[12.5px] leading-[1.55] text-text-dim">
        {description}
      </p>

      <StateActions
        className="pt-5"
        primary={
          primaryAction && {
            label: primaryAction.label,
            onClick: primaryAction.onClick,
            href: primaryAction.href,
            icon:
              primaryAction.shape !== "neutral" ? (
                <Plus size={12} className="text-bg" />
              ) : undefined,
          }
        }
        secondary={
          secondaryAction && {
            ...secondaryAction,
            icon: secondaryAction.external ? (
              <ArrowUpRight size={12} className="text-text-faint" />
            ) : undefined,
          }
        }
      />
    </div>
  );
}
