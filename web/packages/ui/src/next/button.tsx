import { cn } from "../lib/utils";

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger" | "inverse" | "inverse-quiet";
export type ButtonSize = "sm" | "md" | "lg";

const BASE =
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-n-control font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-n-ink disabled:pointer-events-none disabled:opacity-50";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-n-ink text-n-on-ink hover:opacity-90",
  secondary: "border border-n-line bg-n-surface text-n-text-1 hover:bg-n-fill-1",
  quiet: "text-n-text-3 hover:text-n-text-1",
  danger: "text-n-no-fg hover:bg-n-no-bg",
  inverse: "bg-n-on-ink text-n-ink hover:opacity-90 focus-visible:outline-n-on-ink",
  "inverse-quiet": "text-n-on-ink/60 hover:text-n-on-ink focus-visible:outline-n-on-ink",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "n-meta h-6 px-2",
  md: "n-body h-8 px-3",
  lg: "text-[15px] leading-[1.3] h-11 px-4",
};

export function buttonClass(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  className?: string,
) {
  return cn(BASE, VARIANT[variant], SIZE[size], className);
}

export interface ButtonProps extends React.ComponentProps<"button"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** false for a person who can't make this change: the control is absent, never disabled */
  canEdit?: boolean;
}

export function Button({
  variant = "primary",
  size = "md",
  canEdit = true,
  className,
  type = "button",
  ...props
}: ButtonProps) {
  if (!canEdit) return null;
  return <button type={type} className={buttonClass(variant, size, className)} {...props} />;
}

export function IconButton({
  className,
  type = "button",
  ...props
}: React.ComponentProps<"button"> & { "aria-label": string }) {
  return (
    <button
      type={type}
      className={cn(
        BASE,
        "size-[30px] text-n-text-2 hover:bg-n-fill-1 hover:text-n-text-1 aria-expanded:bg-n-fill-1",
        className,
      )}
      {...props}
    />
  );
}
