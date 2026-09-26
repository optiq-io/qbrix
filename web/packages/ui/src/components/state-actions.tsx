import type { ReactNode } from "react";
import { cn } from "../lib/utils";

// the action row a full-page state offers. board `APP · Empty, loading & error
// states` draws it six times — three empty states, the gated state and the
// error state — and every one is the same box:
//
//   h32 · r8 · px 13 · gap 6
//   primary   $accent ground, label 12/600 on $bg
//   secondary $bg-panel ground, $border-strong outline, label 12/500
//
// it is deliberately **not** the published `Button / Primary` (h36 r18 pill,
// 14.5/600) — that is the page-level action, this is the compact one inside a
// state. shared rather than inlined because six states in two tickets need the
// identical shape, and two hand-rolled copies would drift.

const BOX = "flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-[13px] transition-colors";

export type StateAction = {
  label: string;
  onClick?: () => void;
  href?: string;
  /** rendered before the label on the primary, after it on the secondary —
      which is what the board draws (a leading `plus`, a trailing arrow) */
  icon?: ReactNode;
  external?: boolean;
};

function Primary({ action }: { action: StateAction }) {
  const content = (
    <>
      {action.icon}
      <span className="font-sans text-[12px] font-semibold text-bg">
        {action.label}
      </span>
    </>
  );
  const className = cn(BOX, "bg-accent hover:bg-accent/90");

  return action.href ? (
    <a href={action.href} className={className}>
      {content}
    </a>
  ) : (
    <button type="button" onClick={action.onClick} className={className}>
      {content}
    </button>
  );
}

function Secondary({ action }: { action: StateAction }) {
  const content = (
    <>
      <span className="font-sans text-[12px] font-medium text-text-secondary">
        {action.label}
      </span>
      {action.icon}
    </>
  );
  const className = cn(
    BOX,
    "border border-border-strong bg-bg-panel hover:border-border-strong/70",
  );

  return action.href ? (
    <a
      href={action.href}
      target={action.external ? "_blank" : undefined}
      rel={action.external ? "noopener noreferrer" : undefined}
      className={className}
    >
      {content}
    </a>
  ) : (
    <button type="button" onClick={action.onClick} className={className}>
      {content}
    </button>
  );
}

export function StateActions({
  primary,
  secondary,
  className,
}: {
  primary?: StateAction;
  /** the event-log empty state draws a secondary with no primary, so both
      slots are independent */
  secondary?: StateAction;
  className?: string;
}) {
  if (!primary && !secondary) return null;

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {primary && <Primary action={primary} />}
      {secondary && <Secondary action={secondary} />}
    </div>
  );
}
