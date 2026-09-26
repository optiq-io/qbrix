import type { ContextSchema, GateRule, Policy } from "@/lib/api/types";

// the payload rules for creating an experiment, kept out of the form.
//
// these are the parts that are easy to get subtly wrong and impossible to see
// in a render tree: which policies are even offered for a reward type, and what
// `policy_params` means for `auto` versus a named policy — they are not the
// same shape, and sending the wrong one is a 400 the user cannot act on.

export type RewardType = "binary" | "bounded" | "continuous";

export const REWARD_TYPES: {
  value: RewardType;
  label: string;
  hint: string;
}[] = [
  { value: "binary", label: "Binary", hint: "Click, convert, yes/no" },
  { value: "bounded", label: "Bounded", hint: "A score in a fixed range" },
  { value: "continuous", label: "Continuous", hint: "Revenue, duration" },
];

export const AUTO_POLICY_NAME = "auto";

/** surfaced as the default choice. the backend resolves `policy: "auto"` into a
 *  scoped meta-bandit portfolio from the reward type and context settings sent
 *  in `policy_params` — it is not a policy that exists in the catalog. */
export const AUTO_POLICY: Policy = {
  name: AUTO_POLICY_NAME,
  category: "meta",
  reward_types: ["binary", "bounded", "continuous"],
  description:
    "Runs several strategies in parallel and shifts traffic toward whichever is learning fastest, scoped to your reward type and context settings.",
  user_params: [],
};

/** a policy is offered only if it accepts this reward type, and context is
 *  all-or-nothing: contextual policies need a schema, and non-contextual ones
 *  cannot use one. */
export function eligiblePolicies(
  all: Policy[],
  rewardType: RewardType | "",
  useContext: boolean,
): Policy[] {
  return all.filter((p) => {
    if (rewardType && !p.reward_types.includes(rewardType)) return false;
    return useContext ? p.category === "contextual" : p.category !== "contextual";
  });
}

/** `policy_params` carries two unrelated things depending on the choice.
 *
 *  For `auto` it is the *scope* the server needs to assemble a portfolio.
 *  For a named policy it is that policy's own user params, parsed to numbers.
 *  Either way the context schema rides along when context is on — and `dim` is
 *  derived from the schema server-side, so sending both is an error. */
export function buildPolicyParams(input: {
  policy: string;
  catalogPolicy: Policy | undefined;
  rewardType: RewardType | "";
  useContext: boolean;
  contextSchema: ContextSchema;
  values: Record<string, string>;
}): Record<string, unknown> | undefined {
  const { policy, catalogPolicy, rewardType, useContext, contextSchema, values } =
    input;

  if (policy === AUTO_POLICY_NAME) {
    return {
      reward_type: rewardType,
      use_context: useContext,
      ...(useContext ? { context_schema: contextSchema } : {}),
    };
  }

  const params: Record<string, unknown> = {};
  for (const param of catalogPolicy?.user_params ?? []) {
    const raw = values[param.name];
    if (raw === undefined || raw === "") continue;
    const parsed =
      param.type === "integer" ? Number.parseInt(raw, 10) : Number.parseFloat(raw);
    if (Number.isNaN(parsed)) continue;
    params[param.name] = parsed;
  }
  // a schema is a creation-level concept like the reward type, never a user
  // param — `PolicyParam.type` is only ever "integer" | "number"
  if (useContext) params.context_schema = contextSchema;

  return Object.keys(params).length > 0 ? params : undefined;
}

/** the defaults a named policy opens on, so its fields are never blank. */
export function defaultParamValues(policy: Policy | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const param of policy?.user_params ?? []) {
    if (param.default !== null && param.default !== undefined) {
      out[param.name] = String(param.default);
    }
  }
  return out;
}

export type GateDraft = {
  enabled: boolean;
  rolloutPercent: string;
  timezone: string;
  defaultArmId: string;
  startDate: string;
  endDate: string;
  activeHoursStart: string;
  activeHoursEnd: string;
  rules: RuleDraft[];
};

export type RuleDraft = {
  id: string;
  key: string;
  operator: GateRule["operator"];
  value: string;
  armId: string;
};

export const GATE_OPERATORS: GateRule["operator"][] = [
  "in",
  "not_in",
  "eq",
  "neq",
  "contains",
  "not_contains",
  "gt",
  "gte",
  "lt",
  "lte",
];

export const emptyGate = (): GateDraft => ({
  enabled: false,
  rolloutPercent: "100",
  timezone: "UTC",
  defaultArmId: "",
  startDate: "",
  endDate: "",
  activeHoursStart: "00:00",
  activeHoursEnd: "23:59",
  rules: [],
});

/** a comma in a rule value means a list — `in` and `not_in` are the only
 *  operators that take one, but splitting is harmless for the rest and matches
 *  what the gate editor already does. */
export function buildGateConfig(gate: GateDraft) {
  if (!gate.enabled) return undefined;
  return {
    enabled: true,
    rollout_percentage: Number.parseInt(gate.rolloutPercent, 10) || 100,
    timezone: gate.timezone,
    default_arm_id: gate.defaultArmId || null,
    schedule_start: gate.startDate || null,
    schedule_end: gate.endDate || null,
    active_hours_start: gate.activeHoursStart || null,
    active_hours_end: gate.activeHoursEnd || null,
    rules: gate.rules
      .filter((r) => r.key.trim())
      .map((r) => ({
        key: r.key.trim(),
        operator: r.operator,
        value: r.value.includes(",")
          ? r.value.split(",").map((v) => v.trim())
          : r.value.trim(),
        arm_id: r.armId || null,
      })),
  };
}
