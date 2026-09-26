import { cn } from "../lib/utils";

type MonoLabelProps = {
  children: React.ReactNode;
  className?: string;
  size?: "xs" | "sm";
  tone?: "primary" | "secondary" | "dim" | "faint" | "accent" | "info" | "danger";
};

const sizeClasses = {
  xs: "text-[10px] tracking-[0.12em]",
  sm: "text-[11px] tracking-[0.1em]",
};

const toneClasses = {
  primary: "text-text-primary",
  secondary: "text-text-secondary",
  dim: "text-text-dim",
  faint: "text-text-faint",
  accent: "text-accent",
  info: "text-info",
  danger: "text-danger",
};

export function MonoLabel({
  children,
  className,
  size = "xs",
  tone = "dim",
}: MonoLabelProps) {
  return (
    <span
      className={cn(
        "font-mono uppercase font-medium",
        sizeClasses[size],
        toneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
