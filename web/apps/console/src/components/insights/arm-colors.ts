import type { ArmStats } from "@/lib/api/types";

// canonical insights palette — color is pinned to arm_index (stable
// identity from the backend) so every chart on the page renders the same
// arm in the same color regardless of sort order or rank.
// the six series hues are the viz tokens (@qbrix/ui globals.css); arms
// beyond six wrap. never inline a viz hex — alpha comes from the
// -dim/-soft token steps or numeric fillOpacity, not string concat.
export const ARM_PALETTE = [
  "var(--color-viz-1)",
  "var(--color-viz-2)",
  "var(--color-viz-3)",
  "var(--color-viz-4)",
  "var(--color-viz-5)",
  "var(--color-viz-6)",
];

export function colorForArmIndex(armIndex: number): string {
  return ARM_PALETTE[armIndex % ARM_PALETTE.length];
}

// build name -> color and index -> color maps for one experiment's arms.
// callers should derive these once at the page level and hand them down
// to every chart so the assignment is consistent.
export function buildArmColorMaps(arms: ArmStats[]) {
  const byName = new Map<string, string>();
  const byIndex = new Map<number, string>();
  for (const arm of arms) {
    const color = colorForArmIndex(arm.arm_index);
    byName.set(arm.arm_name, color);
    byIndex.set(arm.arm_index, color);
  }
  return { byName, byIndex };
}
