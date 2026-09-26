"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { PageHead } from "@qbrix/ui/components/page-head";
import { PageReveal } from "@qbrix/ui/components/page-reveal";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { InlineBanner } from "@qbrix/ui/components/inline-banner";
import { cn } from "@qbrix/ui/lib/utils";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { resolveApiError, type ResolvedApiError } from "@/lib/api/handle-error";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { pools as poolsApi } from "@/lib/api/pools";
import { policies as policiesApi } from "@/lib/api/policies";
import { usePoolDraft } from "@/lib/pools/use-pool-draft";
import { PoolPicker } from "@/components/pools/pool-picker";
import { routes } from "@/config/routes";
import { useToast } from "@qbrix/ui/components/toast";
import type { ContextSchema, Pool } from "@/lib/api/types";
import {
  AUTO_POLICY,
  AUTO_POLICY_NAME,
  buildGateConfig,
  buildPolicyParams,
  defaultParamValues,
  eligiblePolicies,
  emptyGate,
  GATE_OPERATORS,
  REWARD_TYPES,
  type GateDraft,
  type RewardType,
} from "@/lib/experiments/create";
import { ContextSchemaBuilder, schemaReady } from "./context-schema-builder";
import { ChoiceCard, FieldRow, Section, Switch, TextInput } from "./section";

// board `APP · New experiment · ALT A — One page`.
//
// this replaces a four-step modal wizard. creating an experiment fixes its
// pool, its variants, its reward type and its strategy, and none of them can be
// changed afterwards — a queue of four dialogs asked for all four without ever
// showing them together. here they are one page with a summary rail that names
// every fixed decision next to the button that commits them.
//
// sections 3 and 4 open collapsed. they have working defaults (auto, no gate)
// and most experiments never touch them, but their heads still state what they
// currently amount to: collapsed is not the same as hidden.

export function NewExperimentForm({ initialPoolId }: { initialPoolId?: string }) {
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [poolId, setPoolId] = useState(initialPoolId ?? "");
  const [drafting, setDrafting] = useState(false);
  const [createdPool, setCreatedPool] = useState<Pool | null>(null);
  const [rewardType, setRewardType] = useState<RewardType>("binary");
  const [useContext, setUseContext] = useState(false);
  const [contextSchema, setContextSchema] = useState<ContextSchema>([]);
  const [policy, setPolicy] = useState(AUTO_POLICY_NAME);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [gate, setGate] = useState<GateDraft>(emptyGate);
  const [openSections, setOpenSections] = useState({ strategy: false, gate: false });
  const [error, setError] = useState<ResolvedApiError | null>(null);

  const draft = usePoolDraft();

  const poolsQuery = useQuery({
    queryKey: queryKeys.pools.list({ limit: 100 }),
    queryFn: () => poolsApi.list({ limit: 100 }),
  });
  const policiesQuery = useQuery({
    queryKey: queryKeys.policies.all,
    queryFn: () => policiesApi.list(),
  });

  const ready = usePageReady([poolsQuery, policiesQuery]);
  const pools = poolsQuery.data?.pools ?? [];
  const allPolicies = policiesQuery.data?.policies ?? [];

  const eligible = useMemo(
    () => eligiblePolicies(allPolicies, rewardType, useContext),
    [allPolicies, rewardType, useContext],
  );
  const catalogPolicy = allPolicies.find((p) => p.name === policy);
  const selectedPool =
    createdPool ?? pools.find((p) => p.id === poolId) ?? null;
  const poolArms = selectedPool?.arms ?? [];

  // a concrete policy is scoped to a reward type and to whether context is on,
  // so changing either can strand the choice on something now ineligible. auto
  // accepts everything, which is why it is what we fall back to.
  function retarget(next: { rewardType?: RewardType; useContext?: boolean }) {
    const nextReward = next.rewardType ?? rewardType;
    const nextContext = next.useContext ?? useContext;
    if (next.rewardType !== undefined) setRewardType(next.rewardType);
    if (next.useContext !== undefined) setUseContext(next.useContext);

    if (policy === AUTO_POLICY_NAME) return;
    const stillEligible = eligiblePolicies(allPolicies, nextReward, nextContext).some(
      (p) => p.name === policy,
    );
    if (!stillEligible) {
      setPolicy(AUTO_POLICY_NAME);
      setParamValues({});
    }
  }

  function selectPolicy(nextName: string) {
    setPolicy(nextName);
    setParamValues(
      defaultParamValues(allPolicies.find((p) => p.name === nextName)),
    );
  }

  const poolReady = drafting ? draft.ready : !!createdPool || !!poolId;
  const contextOk = !useContext || schemaReady(contextSchema);
  const canCreate = !!name.trim() && poolReady && contextOk;

  const create = useMutation({
    mutationFn: async () => {
      // the pool has to exist before the experiment can point at it. if the
      // experiment then fails we must not create the pool again on retry, so it
      // is held and the picker switches to showing it as chosen.
      let targetPoolId = createdPool?.id ?? poolId;
      if (drafting && !createdPool) {
        const pool = await draft.submit();
        setCreatedPool(pool);
        queryClient.invalidateQueries({ queryKey: queryKeys.pools.all });
        targetPoolId = pool.id;
      }

      return experimentsApi.create({
        name: name.trim(),
        pool_id: targetPoolId,
        policy,
        policy_params: buildPolicyParams({
          policy,
          catalogPolicy,
          rewardType,
          useContext,
          contextSchema,
          values: paramValues,
        }),
        feature_gate: buildGateConfig(gate),
      });
    },
    onSuccess: (experiment) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.experiments.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.pools.all });
      toast.success("Experiment created");
      router.push(routes.experimentOverview(experiment.id));
    },
    onError: (err) =>
      setError(resolveApiError(err, "Failed to create the experiment")),
  });

  const strategyLabel = policy === AUTO_POLICY_NAME ? "Auto" : policy;
  const gateLabel = gate.enabled
    ? `${gate.rolloutPercent}%${gate.rules.length ? ` · ${gate.rules.length} rule${gate.rules.length === 1 ? "" : "s"}` : ""}`
    : "Not set — every request is eligible";

  return (
    <div className="flex flex-1 flex-col">
      <PageHead
        title="New experiment"
        meta="Everything this experiment will ever be fixed on, on one page."
      />

      <PageReveal
        ready={ready}
        skeleton={
          <div className="flex gap-5 px-7 pb-7">
            <div className="flex flex-1 flex-col gap-3.5">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-[120px] w-full rounded-[12px]" />
              ))}
            </div>
            <Skeleton className="h-[300px] w-[320px] rounded-[12px]" />
          </div>
        }
      >
        <div className="flex flex-1 items-start gap-5 px-7 pb-7">
          <div className="flex min-w-0 flex-1 flex-col gap-3.5">
            <Section step={1} title="Basics">
              <FieldRow label="Name">
                <TextInput
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="checkout-cta"
                  autoFocus
                />
              </FieldRow>

              <div className="flex flex-col gap-2 pt-1">
                <span className="text-[13px] text-text-dim">Pool</span>
                <PoolPicker
                  pools={pools}
                  value={poolId}
                  onChange={setPoolId}
                  drafting={drafting}
                  onDraftingChange={setDrafting}
                  draft={draft}
                  createdPool={createdPool}
                />
              </div>
            </Section>

            <Section step={2} title="Reward & context">
              <div className="flex gap-2.5">
                {REWARD_TYPES.map((r) => (
                  <ChoiceCard
                    key={r.value}
                    title={r.label}
                    hint={r.hint}
                    selected={rewardType === r.value}
                    onSelect={() => retarget({ rewardType: r.value })}
                  />
                ))}
              </div>

              <div className="flex items-center gap-3 pt-1">
                <span className="flex min-w-0 flex-1 flex-col gap-[2px]">
                  <span className="text-[13px] font-medium text-text-primary">
                    Learn from request context
                  </span>
                  <span className="text-[11.5px] text-text-faint">
                    {useContext
                      ? "Send these properties on every select — qbrix encodes them, you never build a vector."
                      : "Off — every request is treated the same."}
                  </span>
                </span>
                <Switch
                  checked={useContext}
                  onChange={(next) => retarget({ useContext: next })}
                  label="Learn from request context"
                />
              </div>

              {useContext && (
                <ContextSchemaBuilder
                  schema={contextSchema}
                  onChange={setContextSchema}
                />
              )}
            </Section>

            <Section
              step={3}
              title="Strategy"
              summary={openSections.strategy ? undefined : strategyLabel}
              collapsible
              open={openSections.strategy}
              onToggle={() =>
                setOpenSections((s) => ({ ...s, strategy: !s.strategy }))
              }
            >
              <ChoiceCard
                title="Auto"
                hint="Runs several strategies and shifts traffic to whichever learns fastest."
                badge="recommended"
                selected={policy === AUTO_POLICY_NAME}
                onSelect={() => selectPolicy(AUTO_POLICY_NAME)}
              />
              <div className="flex flex-col gap-2">
                {eligible.map((p) => (
                  <ChoiceCard
                    key={p.name}
                    title={p.name}
                    hint={p.description}
                    badge={p.category}
                    selected={policy === p.name}
                    onSelect={() => selectPolicy(p.name)}
                  />
                ))}
              </div>

              {policy !== AUTO_POLICY_NAME &&
                (catalogPolicy?.user_params.length ?? 0) > 0 && (
                  <div className="flex flex-col gap-2 pt-1">
                    <span className="text-[13px] font-medium text-text-primary">
                      Parameters
                    </span>
                    <div className="flex flex-col rounded-[10px] border border-border bg-bg-panel">
                      {catalogPolicy?.user_params.map((param, i) => (
                        <div
                          key={param.name}
                          className={cn(
                            "flex items-center gap-3.5 px-3.5 py-2.5",
                            i > 0 && "border-t border-border-subtle",
                          )}
                        >
                          <span className="flex min-w-0 flex-1 flex-col gap-[2px]">
                            <span className="text-[13px] font-medium text-text-primary">
                              {param.name}
                            </span>
                            <span className="text-[11.5px] leading-[1.4] text-text-faint">
                              {param.description}
                            </span>
                          </span>
                          <input
                            value={paramValues[param.name] ?? ""}
                            onChange={(e) =>
                              setParamValues((v) => ({
                                ...v,
                                [param.name]: e.target.value,
                              }))
                            }
                            placeholder={
                              param.default !== null ? String(param.default) : ""
                            }
                            inputMode="decimal"
                            className="w-[88px] shrink-0 rounded-[8px] border border-border bg-bg-overlay px-3 py-2 text-right font-mono text-[13px] text-text-primary outline-none transition-colors placeholder:text-text-faint focus:border-border-strong"
                          />
                        </div>
                      ))}
                    </div>
                    <p className="text-[11.5px] leading-[1.5] text-text-faint">
                      These seed the beliefs the experiment starts from. Editing
                      them later is a no-op until the beliefs are reset, so this is
                      the moment that counts.
                    </p>
                  </div>
                )}
            </Section>

            <GateSection
              gate={gate}
              setGate={setGate}
              arms={poolArms}
              open={openSections.gate}
              onToggle={() => setOpenSections((s) => ({ ...s, gate: !s.gate }))}
              summary={gateLabel}
            />
          </div>

          <aside className="sticky top-6 flex w-[320px] shrink-0 flex-col gap-3">
            <div className="flex flex-col gap-3 rounded-[12px] border border-border-subtle bg-bg-raised p-4">
              <span className="font-mono text-[10.5px] uppercase tracking-[0.09em] text-text-faint">
                What you are creating
              </span>
              <Summary label="Name" value={name || "—"} muted={!name} />
              <Summary
                label="Pool"
                value={
                  drafting && !createdPool
                    ? `${draft.name || "new pool"} · ${draft.variants.length} variants`
                    : selectedPool
                      ? `${selectedPool.name} · ${poolArms.length} variants`
                      : "—"
                }
                muted={!poolReady}
              />
              <Summary
                label="Reward"
                value={
                  REWARD_TYPES.find((r) => r.value === rewardType)?.label ?? "—"
                }
              />
              <Summary
                label="Context"
                value={
                  useContext
                    ? `${contextSchema.length} ${contextSchema.length === 1 ? "property" : "properties"}`
                    : "Off"
                }
              />
              <Summary label="Strategy" value={strategyLabel} />
              <Summary label="Gate" value={gateLabel} muted={!gate.enabled} />
              <div className="h-px w-full bg-border-subtle" />
              <p className="text-[11.5px] leading-[1.5] text-text-faint">
                Pool, variants, reward type and strategy are fixed once this
                exists. Rollout and rules stay editable.
              </p>
            </div>

            {error && (
              <InlineBanner tone="danger">
                <span className="flex flex-col gap-1">
                  <span className="font-medium">{error.message}</span>
                  {error.hint && (
                    <span className="text-[11.5px] opacity-80">{error.hint}</span>
                  )}
                </span>
              </InlineBanner>
            )}

            <button
              type="button"
              onClick={() => {
                setError(null);
                create.mutate();
              }}
              disabled={!canCreate || create.isPending}
              className="flex h-10 items-center justify-center rounded-[10px] bg-accent text-[14px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:pointer-events-none disabled:opacity-50"
            >
              {create.isPending ? "Creating…" : "Create experiment"}
            </button>
            <Link
              href={routes.home}
              className="flex h-[38px] items-center justify-center rounded-[10px] border border-border-subtle text-[13.5px] font-medium text-text-dim transition-colors hover:border-border hover:text-text-secondary"
            >
              Cancel
            </Link>
          </aside>
        </div>
      </PageReveal>
    </div>
  );
}

function Summary({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="w-[82px] shrink-0 text-[12.5px] text-text-faint">
        {label}
      </span>
      <span
        className={cn(
          "min-w-0 flex-1 break-words text-[12.5px] font-medium",
          muted ? "text-text-faint" : "text-text-primary",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function GateSection({
  gate,
  setGate,
  arms,
  open,
  onToggle,
  summary,
}: {
  gate: GateDraft;
  setGate: React.Dispatch<React.SetStateAction<GateDraft>>;
  arms: { id: string; name: string; index: number }[];
  open: boolean;
  onToggle: () => void;
  summary: string;
}) {
  const rollout = Number.parseInt(gate.rolloutPercent, 10) || 0;

  return (
    <Section
      step={4}
      title="Feature gate"
      summary={open ? undefined : summary}
      collapsible
      open={open}
      onToggle={onToggle}
      aside={
        <Switch
          checked={gate.enabled}
          onChange={(next) => setGate((g) => ({ ...g, enabled: next }))}
          label="Put a gate in front of this experiment"
        />
      }
    >
      {!gate.enabled ? (
        <p className="text-[12px] leading-[1.5] text-text-faint">
          Without a gate every request is eligible and the experiment serves all
          of them. Turn one on to hold traffic back while you watch it, or to
          decide who is eligible. A gate can be added at any time.
        </p>
      ) : (
        <>
          <div className="flex items-center gap-4">
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[12.5px] text-text-dim">Rollout</span>
                <span className="font-mono text-[12.5px] text-accent">
                  {rollout}%
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={rollout}
                onChange={(e) =>
                  setGate((g) => ({ ...g, rolloutPercent: e.target.value }))
                }
                aria-label="Rollout percentage"
                className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-bg-hover accent-accent"
              />
            </div>

            <select
              value={gate.defaultArmId}
              onChange={(e) =>
                setGate((g) => ({ ...g, defaultArmId: e.target.value }))
              }
              aria-label="Default variant"
              className="w-[170px] shrink-0 cursor-pointer appearance-none rounded-[8px] border border-border bg-bg-panel px-3 py-2 text-[12.5px] text-text-primary outline-none"
            >
              <option value="">No default variant</option>
              {arms.map((arm) => (
                <option key={arm.id} value={arm.id}>
                  {arm.name}
                </option>
              ))}
            </select>
          </div>

          <p className="text-[11.5px] leading-[1.5] text-text-faint">
            {rollout}% of eligible traffic enters the experiment. The rest is
            served the default variant, as is everyone when it is paused.
          </p>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            {gate.rules.map((rule) => (
              <span
                key={rule.id}
                className="flex items-center gap-2 rounded-[7px] border border-border bg-bg-panel py-[5px] pl-2.5 pr-1.5"
              >
                <input
                  value={rule.key}
                  onChange={(e) =>
                    setGate((g) => ({
                      ...g,
                      rules: g.rules.map((r) =>
                        r.id === rule.id ? { ...r, key: e.target.value } : r,
                      ),
                    }))
                  }
                  placeholder="key"
                  size={Math.max(rule.key.length || 6, 6)}
                  className="bg-transparent font-mono text-[11.5px] text-text-primary outline-none placeholder:text-text-faint"
                />
                <select
                  value={rule.operator}
                  onChange={(e) =>
                    setGate((g) => ({
                      ...g,
                      rules: g.rules.map((r) =>
                        r.id === rule.id
                          ? { ...r, operator: e.target.value as typeof r.operator }
                          : r,
                      ),
                    }))
                  }
                  aria-label="Operator"
                  className="cursor-pointer appearance-none rounded-[5px] bg-bg-hover px-1.5 py-[2px] font-mono text-[11px] text-text-dim outline-none"
                >
                  {GATE_OPERATORS.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                <input
                  value={rule.value}
                  onChange={(e) =>
                    setGate((g) => ({
                      ...g,
                      rules: g.rules.map((r) =>
                        r.id === rule.id ? { ...r, value: e.target.value } : r,
                      ),
                    }))
                  }
                  placeholder="value"
                  size={Math.max(rule.value.length || 8, 8)}
                  className="bg-transparent font-mono text-[11.5px] text-text-secondary outline-none placeholder:text-text-faint"
                />
                <button
                  type="button"
                  onClick={() =>
                    setGate((g) => ({
                      ...g,
                      rules: g.rules.filter((r) => r.id !== rule.id),
                    }))
                  }
                  aria-label="Remove rule"
                  className="shrink-0 text-text-faint transition-colors hover:text-text-primary"
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            <button
              type="button"
              onClick={() =>
                setGate((g) => ({
                  ...g,
                  rules: [
                    ...g.rules,
                    {
                      id: crypto.randomUUID(),
                      key: "",
                      operator: "in" as const,
                      value: "",
                      armId: "",
                    },
                  ],
                }))
              }
              className="flex items-center gap-1.5 rounded-[7px] border border-border-subtle px-2.5 py-[6px] text-[12px] text-text-dim transition-colors hover:border-border hover:text-text-secondary"
            >
              <Plus size={11} />
              Rule
            </button>
          </div>
        </>
      )}
    </Section>
  );
}
