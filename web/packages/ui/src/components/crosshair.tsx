import { cn } from "../lib/utils";

type CrosshairPosition =
  | "top-left"
  | "top-right"
  | "bottom-left"
  | "bottom-right";

type CrosshairProps = {
  position: CrosshairPosition;
  size?: number;
  className?: string;
};

const positionClasses: Record<CrosshairPosition, string> = {
  "top-left": "top-0 left-0 -translate-x-1/2 -translate-y-1/2",
  "top-right": "top-0 right-0 translate-x-1/2 -translate-y-1/2",
  "bottom-left": "bottom-0 left-0 -translate-x-1/2 translate-y-1/2",
  "bottom-right": "bottom-0 right-0 translate-x-1/2 translate-y-1/2",
};

export function Crosshair({ position, size = 8, className }: CrosshairProps) {
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute",
        positionClasses[position],
        className,
      )}
      style={{ width: size, height: size }}
    >
      <span
        className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-border-strong"
      />
      <span
        className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-border-strong"
      />
    </span>
  );
}

type CrosshairCornersProps = {
  className?: string;
};

export function CrosshairCorners({ className }: CrosshairCornersProps) {
  return (
    <span aria-hidden className={cn("contents", className)}>
      <Crosshair position="top-left" />
      <Crosshair position="top-right" />
      <Crosshair position="bottom-left" />
      <Crosshair position="bottom-right" />
    </span>
  );
}
