import type { ArmStats } from "@/lib/api/types";

// derivations shared by the workspace chrome and the Overview body. both read
// the same `queryKeys.insights.arms` cache, so this must agree with itself —
// the "observed leader" chip in the header and the tinted row in the table are
// the same claim rendered twice.

// an arm with no feedback has no observed reward, so it cannot lead. this is
// ordering by *observed* mean only: nothing here knows the learner's posterior.
export function rankedArms(arms: ArmStats[]): ArmStats[] {
  return arms
    .filter((a) => a.avg_reward !== null && (a.feedback_count ?? 0) > 0)
    .sort((a, b) => (b.avg_reward as number) - (a.avg_reward as number));
}

export function leaderOf(arms: ArmStats[]): ArmStats | null {
  return rankedArms(arms)[0] ?? null;
}

export function runnerUpOf(arms: ArmStats[]): ArmStats | null {
  return rankedArms(arms)[1] ?? null;
}

// share of selections, not of feedback — the allocation bar is about where
// traffic went, which is the thing the policy actually controls.
export function selectionShares(arms: ArmStats[]): Map<number, number> {
  const total = arms.reduce((s, a) => s + (a.selections ?? 0), 0);
  const out = new Map<number, number>();
  for (const a of arms) {
    out.set(a.arm_index, total > 0 ? (a.selections ?? 0) / total : 0);
  }
  return out;
}
