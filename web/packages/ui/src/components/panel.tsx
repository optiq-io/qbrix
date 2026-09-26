import { forwardRef } from "react";
import { cn } from "../lib/utils";
import { CrosshairCorners } from "./crosshair";

type PanelVariant = "primary" | "digest" | "surface" | "overlay";

type PanelProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: PanelVariant;
  emphasis?: "default" | "strong";
  crosshair?: boolean;
};

const variantClasses: Record<PanelVariant, string> = {
  primary: "bg-bg-panel",
  digest: "bg-bg-raised",
  surface: "bg-bg-panel",
  overlay: "bg-bg-overlay",
};

export const Panel = forwardRef<HTMLDivElement, PanelProps>(function Panel(
  {
    variant = "primary",
    emphasis = "default",
    crosshair = false,
    className,
    children,
    ...rest
  },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "relative rounded-md border",
        variantClasses[variant],
        emphasis === "strong" ? "border-border-strong" : "border-border-subtle",
        className,
      )}
      {...rest}
    >
      {crosshair ? <CrosshairCorners /> : null}
      {children}
    </div>
  );
});
