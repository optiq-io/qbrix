import { cn } from "../lib/utils";

// board `01 · Components`. the radius is deliberately not uniform: primary and
// secondary are pills (r18 on h36), ghost and icon are r7. hover states are not
// drawn anywhere in the design — these are the minimum a control needs to feel
// live, and the full interaction set is still owed.

type ButtonVariant = "primary" | "secondary" | "ghost";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "h-9 rounded-full bg-accent px-[18px] text-[14.5px] font-semibold text-bg hover:bg-accent/90",
  secondary:
    "h-9 rounded-full border border-border-strong bg-bg-panel px-4 text-[14.5px] font-medium text-text-secondary hover:bg-bg-hover hover:text-text-primary",
  ghost:
    "h-9 rounded-[7px] px-3 text-[13.5px] font-medium text-text-dim hover:bg-bg-hover hover:text-text-secondary",
};

/** the same shape, for the cases where the control has to be an anchor: a
 *  creation action that navigates is a link, not a button, and should behave
 *  like one (middle-click, copy address, prefetch). */
export function buttonClass(variant: ButtonVariant = "primary", className?: string) {
  return cn(BASE, VARIANT[variant], className);
}

const BASE =
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({
  variant = "primary",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(BASE, VARIANT[variant], className)}
      {...props}
    />
  );
}

// square control for a bare glyph — the icon is passed as a child so the caller
// picks its own lucide import and size.
export function IconButton({
  className,
  type = "button",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={cn(
        BASE,
        "size-8 rounded-[7px] border border-border bg-bg-panel text-text-dim hover:bg-bg-hover hover:text-text-secondary",
        className,
      )}
      {...props}
    />
  );
}
