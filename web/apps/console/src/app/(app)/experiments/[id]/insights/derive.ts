import type {
  ArmStats,
  CumulativeRewardPoint,
  Experiment,
  GateConfigResponse,
} from "@/lib/api/types";

// every division here is guarded: an experiment with no feedback yet has
// `avg_reward: null` on every arm and zero selections, and an unguarded ratio
// would render NaN or Infinity into a KPI.

/** the arm the bandit is measured against.
 *
 *  resolved exactly the way the backend does in `AgentService._control_arm`:
 *  the gate's default/committed arm when one is set, otherwise pool arm 0.
 *  matched on id through the pool when it is loaded, falling back to the gate's
 *  own `default_arm_name` — `ArmStats` carries no arm id of its own. */
export function controlArmOf(
  arms: ArmStats[],
  experiment: Experiment | undefined,
): ArmStats | null {
  if (arms.length === 0) return null;

  const gate: GateConfigResponse | null | undefined = experiment?.feature_gate;
  const defaultId = gate?.default_arm_id ?? null;

  if (defaultId) {
    const poolArm = experiment?.pool?.arms.find((a) => a.id === defaultId);
    if (poolArm) {
      const match = arms.find((a) => a.arm_index === poolArm.index);
      if (match) return match;
    }
    const byName = arms.find((a) => a.arm_name === gate?.default_arm_name);
    if (byName) return byName;
  }

  return arms.find((a) => a.arm_index === 0) ?? null;
}

/** highest observed reward rate. arms with no feedback cannot lead. */
export function leaderOf(arms: ArmStats[]): ArmStats | null {
  let best: ArmStats | null = null;
  for (const arm of arms) {
    if (arm.avg_reward === null || arm.feedback_count === 0) continue;
    if (best === null || arm.avg_reward > (best.avg_reward ?? -1)) best = arm;
  }
  return best;
}

/** leader's reward rate as a proportion above the control's.
 *  null whenever the comparison would be meaningless: no control, no leader,
 *  they are the same arm, or the control has never been rewarded. */
export function liftVsControl(
  arms: ArmStats[],
  experiment: Experiment | undefined,
): number | null {
  const control = controlArmOf(arms, experiment);
  const leader = leaderOf(arms);
  if (!control || !leader) return null;
  if (control.arm_index === leader.arm_index) return null;

  const base = control.avg_reward;
  if (base === null || base <= 0) return null;
  return ((leader.avg_reward ?? 0) - base) / base;
}

/** the series is already cumulative, so the total is its last point. */
export function cumulativeTotal(points: CumulativeRewardPoint[]): number {
  return points.length === 0 ? 0 : points[points.length - 1].cumulative_reward;
}

/** the API returns arms in no particular order (observed `1,0,3,2` live), so
 *  every consumer sorts — otherwise stack order and colour drift per bucket. */
export function byArmIndex<T extends { arm_index: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => a.arm_index - b.arm_index);
}
