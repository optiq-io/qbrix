"use client";

import { cn } from "@qbrix/ui/lib/utils";

// boards `APP · Sign in` / `APP · Register`: label mono 11.5/1.6 in
// $text-faint over a h48 r10 $bg-panel shell. the label is typed here rather
// than via MonoLabel because the board's ramp (11.5px, 0.139em) is a step off
// MonoLabel's sm (11px, 0.1em), and this is the spec.
//
// defined outside any form component so react keeps the input mounted across
// renders — inlining it caused focus loss.

export const authLabel =
  "font-mono text-[11.5px] font-medium uppercase tracking-[0.139em] text-text-faint";

export function Field({
  label,
  icon: Icon,
  trailing,
  children,
}: {
  label: string;
  icon: React.ElementType;
  trailing?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className={authLabel}>{label}</span>
        {trailing}
      </div>
      <div className="flex h-12 items-center gap-2.5 rounded-[10px] bg-bg-panel px-3.5 transition-colors focus-within:ring-1 focus-within:ring-border-strong">
        <Icon size={15} className="shrink-0 text-text-dim" />
        {children}
      </div>
    </div>
  );
}

export const fieldInput = cn(
  "min-w-0 flex-1 bg-transparent text-[15.5px] text-text-primary outline-none",
  "placeholder:text-text-faint",
);
