"use client";

import { useCallback, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { useToast } from "@qbrix/ui/components/toast";
import { vizSeries } from "@qbrix/ui/components/belief-viz";
import { cn } from "@qbrix/ui/lib/utils";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { policies as policiesApi } from "@/lib/api/policies";
import { insights as insightsApi } from "@/lib/api/insights";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { useEntitlements } from "@/lib/entitlements";
import type { Policy, PolicyParam } from "@/lib/api/types";
import { ContextSchemaPanel, readContextSchema } from "@/components/experiments/context-schema-panel";
import { ParamField, initialValue, validate } from "../param-field";
import { usePendingEdit } from "../header-actions";
import { ago, num, pct } from "../format";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes } from "@/config/routes";

// board `APP · Experiment / Policy`. two columns on the page ground: the policy
// and its parameters on the left, what training has actually done on the right.
//
// three things the board draws are not built:
//   · `Change` — a policy is fixed at creation by design, like a pool's arms.
//   · `Minimum allocation` / `Batch size` — no policy has either param; batch
//     size is CORTEX_BATCH_SIZE, a service-wide env var.
//   · `Pause learning` — that is `experiment.enabled`, which the header's Pause
//     pill already owns. two controls for one field is a defect.
// and on the right, `Cycles completed` / `Queue depth` / `Avg cycle time` have
// no source: cortex records no training metrics anywhere.

// the API's description is the policy docstring's first line — thin, and empty
// for some (EpsilonPolicy has no docstring). these are the console's own.
const POLICY_DESCRIPTIONS: Record<string, string> = {
  BetaTSPolicy:
    "Samples from Beta posteriors for each arm; favors arms with the highest values. Optimal for binary reward signals and accumulates evidence across selections.",
  GaussianTSPolicy:
    "Thompson Sampling with Gaussian priors. Samples mean estimates from posterior distributions. Best for continuous or bounded reward signals.",
  DiscountedTSPolicy:
    "Thompson Sampling with time-discounting — recent feedback is weighted more heavily. Effective in non-stationary environments.",
  DirichletTSPolicy:
    "Thompson Sampling over a Dirichlet posterior for discrete-outcome rewards. Each observation is an integer bucket rather than a single value.",
  UCB1TunedPolicy:
    "Upper Confidence Bound with variance tuning. Balances exploitation and exploration using a confidence interval derived from empirical variance.",
  KLUCBPolicy:
    "KL-UCB index policy. Asymptotically optimal for Bernoulli bandits by solving a KL-divergence maximization at each step.",
  KLUCBPlusPolicy:
    "KL-UCB+ variant. Uses log(t/N) instead of log(t) in the exploration bonus, which explores less aggressively late in a run.",
  EpsilonPolicy:
    "Epsilon-Greedy: exploit the best arm with probability 1−ε, explore uniformly with probability ε. Simple and reliable baseline.",
  MOSSPolicy:
    "Minimax Optimal Strategy for Stochastic bandits. Horizon-aware confidence bounds; requires knowing T in advance.",
  MOSSAnyTimePolicy:
    "MOSS without horizon knowledge. Adaptive confidence bounds make it effective when total steps are unknown.",
  LinUCBPolicy:
    "Linear UCB for contextual bandits. Maintains a ridge-regression model per arm and selects via UCB over the predicted reward.",
  LinTSPolicy:
    "Linear Thompson Sampling. Samples regression weights from the posterior and picks the arm with the highest expected reward given context.",
  LogisticTSPolicy:
    "Logistic Thompson Sampling for binary contextual rewards. Fits a logistic model per arm; posteriors approximated via Laplace.",
  GLMUCBPolicy:
    "GLM-UCB for generalized linear models. Extends UCB to non-linear reward models via GLM parameter confidence sets.",
  EXP3Policy:
    "Exponential weights for adversarial bandits. Updates arm weights proportionally to observed rewards with no stochastic assumptions.",
  EXP3IXPolicy:
    "EXP3 with importance-weighted exploration. Reduced variance estimator; more sample-efficient than standard EXP3.",
  FPLPolicy:
    "Follow the Perturbed Leader. Adds Gumbel noise to cumulative rewards at each step; low regret in adversarial settings.",
  RandomPolicy:
    "Uniform random selection. No learning — a baseline for measuring what any adaptive policy is worth.",
  MetaBanditPolicy:
    "Auto-selects and weights multiple sub-policies via a bandit-over-bandits approach. Traffic is routed to the best performer.",
};

// stable identities — these feed useCallback deps, and a fresh {} each render
// would re-register the header actions forever
const NO_PARAMS: Record<string, unknown> = {};
const NO_USER_PARAMS: PolicyParam[] = [];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[17px] font-semibold tracking-[-0.3px] text-text-primary">
      {children}
    </h2>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-border-subtle py-[11px]">
      <span className="text-[14px] text-text-dim">{k}</span>
      <span className="text-right text-[14px] text-text-secondary">{v}</span>
    </div>
  );
}

export default function PolicyTabPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <GuardedRoute
      surface="experiment.policy"
      backHref={routes.experimentOverview(id)}
      overviewHref={routes.experimentOverview(id)}
    >
      <PolicyTabPageContent />
    </GuardedRoute>
  );
}

function PolicyTabPageContent() {
  const params = useParams();
  const experimentId = params.id as string;
  const toast = useToast();
  const toastApiError = useApiErrorToast();
  const queryClient = useQueryClient();
  const { hasInsights } = useEntitlements();

  const [draft, setDraft] = useState<Record<string, string>>({});

  const experimentQuery = useQuery({
    queryKey: queryKeys.experiments.detail(experimentId),
    queryFn: () => experimentsApi.get(experimentId),
  });
  const experiment = experimentQuery.data;

  const policiesQuery = useQuery({
    queryKey: queryKeys.policies.list(),
    queryFn: () => policiesApi.list(),
  });
  const policiesData = policiesQuery.data;

  // same key the layout already polls — one request, not two
  const statsQuery = useQuery({
    queryKey: queryKeys.insights.experiment(experimentId),
    queryFn: () => insightsApi.getStats(experimentId),
    enabled: hasInsights,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
  const expStats = statsQuery.data;

  const ready = usePageReady([experimentQuery, policiesQuery, statsQuery]);

  const policy: Policy | undefined = policiesData?.policies.find(
    (p) => p.name === experiment?.policy,
  );
  const currentParams = experiment?.policy_params ?? NO_PARAMS;
  const contextSchema = useMemo(() => readContextSchema(currentParams), [currentParams]);

  // dim is UserConfigurable on every contextual policy, so it arrives in
  // user_params alongside alpha — but it is structural, not a tunable: it
  // shapes the learned arrays, and the server rejects a change with
  // CONTEXT_DIM_IMMUTABLE. offering the input would only ever produce a 409.
  const userParams = useMemo(
    () => (policy?.user_params ?? NO_USER_PARAMS).filter((p) => p.name !== "dim"),
    [policy],
  );
  const contextDim =
    typeof currentParams.dim === "number" ? currentParams.dim : null;

  const valueOf = useCallback(
    (p: PolicyParam) => draft[p.name] ?? initialValue(p, currentParams),
    [draft, currentParams],
  );

  const errors = useMemo(() => {
    const out: Record<string, string | null> = {};
    for (const p of userParams) out[p.name] = validate(p, valueOf(p));
    return out;
  }, [userParams, valueOf]);

  const hasError = Object.values(errors).some(Boolean);
  const isDirty = userParams.some(
    (p) =>
      draft[p.name] !== undefined &&
      draft[p.name] !== initialValue(p, currentParams),
  );

  const saveMutation = useMutation({
    mutationFn: () => {
      // update replaces policy_params wholesale and validates by constructing
      // the policy's param state, so an unknown key is a 400 — build the
      // payload from user_params and carry anything else through untouched.
      const known = new Set(userParams.map((p) => p.name));
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(currentParams)) {
        if (!known.has(k)) payload[k] = v;
      }
      for (const p of userParams) {
        const s = valueOf(p).trim();
        // absent is deliberate: the server fills the default
        if (s !== "") payload[p.name] = Number(s);
      }
      return experimentsApi.update(experimentId, { policy_params: payload });
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(
        queryKeys.experiments.detail(experimentId),
        updated,
      );
      // Home renders from the list — keep its row in step
      queryClient.invalidateQueries({ queryKey: queryKeys.experiments.all });
      setDraft({});
      toast.success("Policy parameters saved");
    },
    onError: (err) => toastApiError(err, "Failed to save parameters"),
  });

  // `mutate` is stable across renders; the mutation object is not, and a new
  // identity here would re-register the header actions on every render
  const { mutate: save, isPending: saving } = saveMutation;
  const onSave = useCallback(() => save(), [save]);
  const onDiscard = useCallback(() => setDraft({}), []);

  usePendingEdit(
    isDirty ? { onSave, onDiscard, saving, saveDisabled: hasError } : null,
  );

  // policies that accept at least one of the same reward types. the current
  // policy leads the list; it cannot be swapped, so this is a readout of what
  // else would take this reward signal, not a picker.
  const compatible = useMemo(() => {
    if (!policy) return [];
    const accepted = new Set(policy.reward_types);
    const rest = (policiesData?.policies ?? [])
      .filter(
        (p) =>
          p.name !== policy.name &&
          p.reward_types.some((rt) => accepted.has(rt)),
      )
      .sort(
        (a, b) =>
          Number(a.category !== policy.category) -
            Number(b.category !== policy.category) ||
          a.name.localeCompare(b.name),
      );
    return [policy, ...rest];
  }, [policiesData, policy]);

  if (!ready) {
    return (
      <div className="flex flex-1">
        <div className="flex min-w-0 flex-1 flex-col gap-3.5 pb-6 pl-7 pr-8 pt-6">
          <Skeleton className="h-[22px] w-24" />
          <Skeleton className="h-[86px] w-full rounded-[14px]" />
          <Skeleton className="mt-4 h-[22px] w-28" />
          <Skeleton className="h-24 w-full" />
        </div>
        <aside className="flex w-[360px] shrink-0 flex-col gap-3.5 border-l border-border-subtle px-[22px] py-6">
          <Skeleton className="h-[22px] w-24" />
          <Skeleton className="h-40 w-full" />
        </aside>
      </div>
    );
  }

  const policyName = experiment?.policy ?? "—";
  const description =
    POLICY_DESCRIPTIONS[policyName] ?? policy?.description ?? "";
  const feedbackRate =
    expStats && expStats.total_selections > 0
      ? pct(expStats.total_feedback / expStats.total_selections)
      : "—";

  return (
    <div className="flex flex-1">
      <div className="flex min-w-0 flex-1 flex-col pb-6 pl-7 pr-8 pt-6">
        <SectionLabel>Policy</SectionLabel>

        <div className="mt-3.5 flex items-center gap-[18px] rounded-[14px] border border-accent-dim bg-accent-soft p-5">
          <span className="size-2.5 shrink-0 rounded-full bg-accent" />
          <div className="flex min-w-0 flex-col gap-1.5">
            <p className="text-[17px] font-semibold tracking-[-0.3px] text-text-primary">
              {policyName}
              {policy && (
                <span className="text-text-dim"> · {policy.category}</span>
              )}
            </p>
            {description && (
              <p className="text-[14px] leading-[1.45] text-text-dim">
                {description}
              </p>
            )}
          </div>
        </div>

        <div className="mt-[30px]">
          <SectionLabel>Parameters</SectionLabel>
        </div>

        {/* policy_params is initialisation config. motor and cortex only read
            it when the redis param blob is absent — ExperimentService.reset_
            experiment says as much, and driving traffic confirms it: cortex
            retrains and rewrites the blob with the *old* values. so saving a
            new prior on a running experiment changes nothing until a reset,
            and the user has no other way to learn that. */}
        {userParams.length > 0 && (
          <p className="mt-2 max-w-[620px] text-[13.5px] leading-[1.5] text-text-dim">
            These are the values the experiment initialises from. A run already
            under way keeps its learned state; new values take effect when its
            beliefs are reset.
          </p>
        )}

        <div className="mt-[22px] flex flex-col">
          {userParams.length > 0 ? (
            userParams.map((p) => (
              <ParamField
                key={p.name}
                param={p}
                value={valueOf(p)}
                // surfaced once anything is dirty, so a required field left
                // empty explains why Save is refusing
                error={isDirty ? errors[p.name] : null}
                onChange={(v) =>
                  setDraft((prev) => ({ ...prev, [p.name]: v }))
                }
              />
            ))
          ) : (
            <p className="border-t border-border-subtle py-5 text-[13.5px] leading-[1.5] text-text-faint">
              {policyName === "MetaBanditPolicy"
                ? "Parameters are managed by the meta-bandit, which selects and weights its sub-policies automatically."
                : "This policy has no configurable parameters."}
            </p>
          )}
        </div>

        {/* schema-backed experiments get the width from ContextSchemaPanel,
            which shows how it was derived; this is the escape hatch's only
            readout of it. */}
        {!contextSchema && contextDim !== null && (
          <div className="mt-[22px] flex flex-col">
            <Row k="Context width" v={contextDim} />
            <p className="mt-1.5 max-w-[620px] text-[12px] leading-[1.5] text-text-faint">
              Every select must send a vector of exactly this width. It is fixed
              for the life of the experiment — the learned parameters are shaped
              by it, so changing it would invalidate everything trained so far.
            </p>
          </div>
        )}

        {contextSchema && <ContextSchemaPanel schema={contextSchema} />}
      </div>

      <aside className="flex w-[360px] shrink-0 flex-col border-l border-border-subtle px-[22px] py-6">
        <SectionLabel>Training</SectionLabel>
        <div className="mt-3.5 flex flex-col">
          <Row
            k="Accepts"
            v={policy ? policy.reward_types.join(", ") : "—"}
          />
          {hasInsights && expStats && (
            <>
              <Row k="Feedback events" v={num(expStats.total_feedback)} />
              <Row k="Selections" v={num(expStats.total_selections)} />
              <Row k="Feedback rate" v={feedbackRate} />
              <Row k="Last selection" v={ago(expStats.last_selection_ms)} />
            </>
          )}
        </div>

        <div className="mt-[30px]">
          <SectionLabel>Compatible policies</SectionLabel>
        </div>
        <div className="mt-3.5 flex flex-col">
          {compatible.map((p, i) => (
            <div
              key={p.name}
              className={cn(
                "flex h-10 items-center gap-3 rounded-[10px] px-3",
                i === 0 && "bg-accent-soft",
              )}
            >
              <span
                className={cn("size-[7px] shrink-0 rounded-full", vizSeries(i))}
              />
              <span
                className={cn(
                  "truncate text-[14.5px]",
                  i === 0
                    ? "font-medium text-text-primary"
                    : "text-text-secondary",
                )}
              >
                {p.name}
              </span>
              <span className="ml-auto shrink-0 text-[12.5px] text-text-faint">
                {p.category}
              </span>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
