import { cn } from "../lib/utils";

type AccentDotProps = {
  active?: boolean;
  size?: number;
  tone?: "accent" | "info" | "danger" | "positive" | "secondary" | "faint";
  className?: string;
};

const toneFills = {
  accent: "bg-accent",
  info: "bg-info",
  danger: "bg-danger",
  positive: "bg-positive",
  secondary: "bg-text-secondary",
  faint: "bg-text-faint",
};

const toneRings = {
  accent: "border-accent/40",
  info: "border-info/40",
  danger: "border-danger/40",
  positive: "border-positive/40",
  secondary: "border-text-dim",
  faint: "border-text-faint",
};

export function AccentDot({
  active = true,
  size = 6,
  tone = "accent",
  className,
}: AccentDotProps) {
  return (
    <span
      className={cn(
        "inline-block rounded-full",
        active ? toneFills[tone] : cn("border bg-transparent", toneRings[tone]),
        className,
      )}
      style={{ width: size, height: size }}
    />
  );
}
