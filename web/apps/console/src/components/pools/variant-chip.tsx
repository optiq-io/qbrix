import { vizSeries } from "@qbrix/ui/components/belief-viz";
import { cn } from "@qbrix/ui/lib/utils";

// one variant, colour-pinned to its index. the colour is the same one the belief
// curves and allocation bars use, so a variant keeps its identity across every
// surface that names it.

export function VariantChip({
  name,
  index,
  size = "md",
}: {
  name: string;
  index: number;
  /** `sm` is the inline form, where chips sit inside a field row */
  size?: "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center rounded-[14px] bg-white/[0.03]",
        size === "md" ? "gap-[7px] px-2.5 py-1" : "gap-[5px] rounded-[6px] px-2 py-[2px]",
      )}
    >
      <span
        className={cn(
          "shrink-0 rounded-full",
          size === "md" ? "size-[7px]" : "size-[5px]",
          vizSeries(index),
        )}
      />
      <span
        className={cn(
          "text-text-secondary",
          size === "md" ? "text-[13px]" : "text-[11.5px]",
        )}
      >
        {name}
      </span>
    </span>
  );
}
