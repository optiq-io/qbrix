"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Minus, Plus, X } from "lucide-react";
import { ConfirmDialog } from "@qbrix/ui/components/confirm-dialog";
import { Skeleton } from "@qbrix/ui/components/skeleton";
import { useToast } from "@qbrix/ui/components/toast";
import { vizSeries } from "@qbrix/ui/components/belief-viz";
import { cn } from "@qbrix/ui/lib/utils";
import { queryKeys } from "@/lib/api/query-keys";
import { usePageReady } from "@/lib/api/page-ready";
import { experiments as experimentsApi } from "@/lib/api/experiments";
import { gates as gatesApi } from "@/lib/api/gates";
import { insights as insightsApi } from "@/lib/api/insights";
import { useEntitlements } from "@/lib/entitlements";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { ApiError } from "@/lib/api/types";
import type {
  GateConfigResponse,
  GateEvaluateResponse,
  GateUpdateRequest,
} from "@/lib/api/types";
import { leaderOf } from "../derive";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes } from "@/config/routes";

// board `APP · Experiment / Gate`. the drawn Bucketing key select is omitted:
// GateConfigResponse has no such field and is_in_rollout hashes context_id
// unconditionally, so the control would be decorative.
const OPERATORS = [
  "eq",
  "neq",
  "in",
  "not_in",
  "contains",
  "not_contains",
  "gt",
  "gte",
  "lt",
  "lte",
] as const;

type RuleRow = {
  uid: string;
  key: string;
  operator: string;
  value: string;
  // the editor cannot author an arm pin, but a rule created through the API can
  // carry one — round-trip it so saving the board does not strip it.
  armId: string | null;
  armName: string | null;
};

const SAMPLE = `{
  "user_id": "u_8241",
  "device": "mobile",
  "country": "NL"
}`;

function toRows(config: GateConfigResponse | undefined): RuleRow[] {
  return (config?.rules ?? []).map((r) => ({
    uid: crypto.randomUUID(),
    key: r.key,
    operator: r.operator,
    value: typeof r.value === "string" ? r.value : JSON.stringify(r.value),
    armId: r.arm_id ?? null,
    armName: r.arm_name ?? null,
  }));
}

// the API stores rule values as arbitrary JSON; the row editor is a text field.
// `in`/`not_in` mean a list, so a bare "NL, BE" has to become an array or the
// operator silently never matches.
function parseValue(operator: string, raw: string): unknown {
  const trimmed = raw.trim();
  if (operator === "in" || operator === "not_in") {
    return trimmed
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed);
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  return trimmed;
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-8 py-4">
      <div className="flex min-w-0 max-w-[420px] flex-col gap-1">
        <span className="text-[14px] font-medium text-text-primary">{label}</span>
        {hint && <span className="text-[12.5px] leading-[1.5] text-text-faint">{hint}</span>}
      </div>
      <div className="flex shrink-0 items-center gap-3">{children}</div>
    </div>
  );
}

const INPUT =
  "h-[34px] rounded-[7px] border border-border-subtle bg-bg-panel px-2.5 text-[13.5px] text-text-primary outline-none focus:border-border-strong";

export default function GateTabPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <GuardedRoute
      surface="experiment.gate"
      backHref={routes.experimentOverview(id)}
      overviewHref={routes.experimentOverview(id)}
    >
      <GateTabPageContent />
    </GuardedRoute>
  );
}

function GateTabPageContent() {
  const params = useParams();
  const experimentId = params.id as string;
  const toast = useToast();
  const toastApiError = useApiErrorToast();
  const queryClient = useQueryClient();
  const { hasInsights } = useEntitlements();

  const experimentQuery = useQuery({
    queryKey: queryKeys.experiments.detail(experimentId),
    queryFn: () => experimentsApi.get(experimentId),
  });
  const experiment = experimentQuery.data;

  // only a 404 means "no gate" — `config` is what decides POST vs PATCH below, so
  // swallowing any other failure into null makes the next save a create against
  // an experiment that already has one, which the API rejects as a conflict.
  const configQuery = useQuery({
    queryKey: queryKeys.gates.detail(experimentId),
    queryFn: () =>
      gatesApi.getConfig(experimentId).catch((err) => {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }),
    retry: false,
  });
  const config = configQuery.data;

  const armsQuery = useQuery({
    queryKey: queryKeys.insights.arms(experimentId),
    queryFn: () => insightsApi.getArmStats(experimentId),
    enabled: hasInsights,
  });
  const armAnalytics = armsQuery.data;

  // the arms feed the leader callout and the default-arm picker, and the
  // experiment feeds the variant list — waiting only on `config` left both to
  // arrive after the form had already drawn.
  const ready = usePageReady([experimentQuery, configQuery, armsQuery]);

  const arms = experiment?.pool?.arms ?? [];
  const leader = leaderOf(armAnalytics?.arms ?? []);

  const [enabled, setEnabled] = useState(false);
  const [rollout, setRollout] = useState(100);
  const [rules, setRules] = useState<RuleRow[]>([]);
  const [commitOpen, setCommitOpen] = useState(false);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [resumeRollout, setResumeRollout] = useState(100);
  const [commitArm, setCommitArm] = useState("");
  const [sample, setSample] = useState(SAMPLE);
  const [evaluation, setEvaluation] = useState<GateEvaluateResponse | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);

  useEffect(() => {
    if (!config) return;
    setEnabled(config.enabled);
    setRollout(config.rollout_percentage);
    setRules(toRows(config));
  }, [config]);

  // a commit is all three of these together — writing default_arm_id alone
  // leaves in-rollout traffic on the bandit, which is the whole trap here.
  const committed =
    !!config && config.enabled && config.rollout_percentage === 0 && !!config.default_arm_id;

  useEffect(() => {
    if (commitArm || arms.length === 0) return;
    const preferred = leader
      ? arms.find((a) => a.index === leader.arm_index)
      : undefined;
    setCommitArm((preferred ?? arms[0]).id);
  }, [arms, leader, commitArm]);

  // what the board actually owns. everything else on the gate — schedule, active
  // hours, timezone — is API-only, so a save must not mention it: on PATCH an
  // absent field is left as stored, and naming it here would erase it.
  const owned = (over: Partial<GateUpdateRequest> = {}): GateUpdateRequest => ({
    enabled,
    rollout_percentage: rollout,
    rules: rules
      .filter((r) => r.key.trim())
      .map((r) => ({
        key: r.key.trim(),
        operator: r.operator,
        value: parseValue(r.operator, r.value),
        arm_id: r.armId,
        arm_name: r.armName,
      })),
    ...over,
  });

  const write = useMutation({
    mutationFn: (over: Partial<GateUpdateRequest> = {}) =>
      config
        ? gatesApi.updateConfig(experimentId, owned(over))
        : gatesApi.createConfig(experimentId, {
            default_arm_id: null,
            ...owned(over),
          }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.gates.detail(experimentId), updated);
      queryClient.invalidateQueries({
        queryKey: queryKeys.experiments.detail(experimentId),
      });
    },
    onError: (err) => toastApiError(err, "Failed to save the gate"),
  });

  const remove = useMutation({
    mutationFn: () => gatesApi.deleteConfig(experimentId),
    onSuccess: () => {
      setRemoveOpen(false);
      toast.success("Feature gate deleted");
      // null is what the query itself resolves to on a 404, so the form falls
      // back to its blank defaults and `write` flips to createConfig
      queryClient.setQueryData(queryKeys.gates.detail(experimentId), null);
      queryClient.invalidateQueries({
        queryKey: queryKeys.experiments.detail(experimentId),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.experiments.all });
      setEnabled(false);
      setRollout(100);
      setRules([]);
      setEvaluation(null);
    },
    onError: (err) => toastApiError(err, "Failed to delete gate"),
  });

  const evaluate = useMutation({
    mutationFn: (metadata: Record<string, unknown>) =>
      gatesApi.evaluate(experimentId, {
        context_id: String(metadata.user_id ?? ""),
        context_metadata: metadata,
      }),
    onSuccess: setEvaluation,
    onError: (err) => toastApiError(err, "Evaluation failed"),
  });

  const dirty = useMemo(() => {
    if (!config) return enabled || rollout !== 100 || rules.length > 0;
    if (enabled !== config.enabled) return true;
    if (rollout !== config.rollout_percentage) return true;
    if (rules.length !== config.rules.length) return true;
    return rules.some((r, i) => {
      const o = config.rules[i];
      return !o || o.key !== r.key.trim() || o.operator !== r.operator;
    });
  }, [config, enabled, rollout, rules]);

  function runEvaluate() {
    try {
      const parsed = JSON.parse(sample);
      setSampleError(null);
      evaluate.mutate(parsed);
    } catch {
      setSampleError("Not valid JSON.");
    }
  }

  if (!ready) {
    return (
      <div className="flex flex-col gap-3 px-7 py-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const committedName =
    arms.find((a) => a.id === config?.default_arm_id)?.name ??
    config?.default_arm_name ??
    "—";

  return (
    <div className="flex flex-col xl:flex-row">
      <div className="flex min-w-0 flex-1 flex-col px-7 pb-8 pt-5">
        {/* commit card — undrawn. the board is a rules editor, but two shipped
            CTAs land here expecting to commit, so it is the headline. built in the drawn status panel's language. */}
        <div
          className={cn(
            "flex items-center gap-3.5 rounded-[12px] px-4 py-3.5",
            committed ? "bg-accent/[0.06]" : "bg-positive/[0.06]",
          )}
        >
          <span
            className={cn(
              "size-2.5 shrink-0 rounded-full",
              committed ? "bg-accent" : "bg-positive",
            )}
          />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-[14.5px] font-medium text-text-primary">
              {committed
                ? `All traffic is pinned to ${committedName}`
                : "The learner is selecting"}
            </span>
            <span className="text-[13px] text-text-dim">
              {committed
                ? "The bandit is not selecting for this experiment."
                : "Commit a variant to send every eligible request to it, without ending the experiment."}
            </span>
          </div>
          {committed ? (
            <button
              type="button"
              onClick={() => {
                setResumeRollout(100);
                setResumeOpen(true);
              }}
              className="h-9 shrink-0 rounded-full bg-bg-hover px-4 text-[14px] font-medium text-text-primary transition-colors hover:bg-white/[0.09]"
            >
              Resume learning
            </button>
          ) : (
            <div className="flex shrink-0 items-center gap-2.5">
              <select
                value={commitArm}
                onChange={(e) => setCommitArm(e.target.value)}
                className={INPUT}
              >
                {arms.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {leader?.arm_index === a.index ? " · leading" : ""}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!commitArm}
                onClick={() => setCommitOpen(true)}
                className="h-9 shrink-0 rounded-full bg-accent px-4 text-[14px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-50"
              >
                Commit via feature gate
              </button>
            </div>
          )}
        </div>

        <h2 className="pb-1 pt-7 text-[15px] font-medium text-text-primary">Exposure</h2>

        <div className="divide-y divide-border-subtle">
          <Field
            label="Gate enabled"
            hint="A disabled gate does no gating at all — every request goes to the learner."
          >
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              onClick={() => setEnabled((v) => !v)}
              className={cn(
                "flex h-6 w-11 shrink-0 items-center rounded-full px-[3px] transition-colors",
                enabled ? "bg-positive" : "bg-bg-hover",
              )}
            >
              <span
                className={cn(
                  "size-[18px] rounded-full bg-bg transition-transform",
                  enabled && "translate-x-5",
                )}
              />
            </button>
          </Field>

          <Field
            label="Rollout"
            hint="Share of matching traffic that enters the experiment. The rest sees the committed variant."
          >
            <input
              type="range"
              min={0}
              max={100}
              value={rollout}
              onChange={(e) => setRollout(Number(e.target.value))}
              className="h-1.5 w-[220px] accent-accent"
            />
            <span className="w-12 text-right font-mono text-[14px] text-text-primary">
              {rollout}%
            </span>
          </Field>
        </div>

        <div className="flex items-center justify-between pb-2 pt-7">
          <h2 className="text-[15px] font-medium text-text-primary">Targeting rules</h2>
          <button
            type="button"
            onClick={() =>
              setRules((r) => [
                ...r,
                {
                  uid: crypto.randomUUID(),
                  key: "",
                  operator: "eq",
                  value: "",
                  armId: null,
                  armName: null,
                },
              ])
            }
            className="flex items-center gap-1 text-[13.5px] text-text-dim transition-colors hover:text-text-primary"
          >
            <Plus size={13} /> Add rule
          </button>
        </div>

        {rules.length === 0 ? (
          <p className="py-3 text-[13px] text-text-faint">
            No rules — every request inside the rollout enters the experiment.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {rules.map((rule, i) => (
              <div key={rule.uid} className="flex flex-col gap-2">
                <div className="flex items-center gap-2 rounded-[10px] border border-border-subtle bg-bg-raised px-3 py-2.5">
                  <span
                    className={cn("size-[7px] shrink-0 rounded-full", vizSeries(i + 1))}
                  />
                  <input
                    value={rule.key}
                    placeholder="attribute"
                    onChange={(e) =>
                      setRules((rs) =>
                        rs.map((r) => (r.uid === rule.uid ? { ...r, key: e.target.value } : r)),
                      )
                    }
                    className={cn(INPUT, "w-[150px]")}
                  />
                  <select
                    value={rule.operator}
                    onChange={(e) =>
                      setRules((rs) =>
                        rs.map((r) =>
                          r.uid === rule.uid ? { ...r, operator: e.target.value } : r,
                        ),
                      )
                    }
                    className={cn(INPUT, "w-[120px]")}
                  >
                    {OPERATORS.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </select>
                  <input
                    value={rule.value}
                    placeholder={
                      rule.operator === "in" || rule.operator === "not_in"
                        ? "NL, BE, DE"
                        : "value"
                    }
                    onChange={(e) =>
                      setRules((rs) =>
                        rs.map((r) =>
                          r.uid === rule.uid ? { ...r, value: e.target.value } : r,
                        ),
                      )
                    }
                    className={cn(INPUT, "min-w-0 flex-1")}
                  />
                  <button
                    type="button"
                    aria-label={`Remove rule ${i + 1}`}
                    onClick={() => setRules((rs) => rs.filter((r) => r.uid !== rule.uid))}
                    className="shrink-0 text-text-faint transition-colors hover:text-danger"
                  >
                    <X size={15} />
                  </button>
                </div>
                {i < rules.length - 1 && (
                  <div className="flex items-center gap-3 px-1">
                    <span className="font-mono text-[11px] tracking-[0.145em] text-text-faint">
                      AND
                    </span>
                    <span className="h-px flex-1 bg-border-subtle" />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-3 pt-7">
          <button
            type="button"
            disabled={!dirty || write.isPending}
            onClick={() => {
              write.mutate(
                {},
                {
                  onSuccess: () => toast.success("Gate saved"),
                },
              );
            }}
            className="h-9 shrink-0 rounded-full bg-accent px-4 text-[14px] font-semibold text-bg transition-colors hover:bg-accent/90 disabled:opacity-40"
          >
            {write.isPending ? "Saving…" : "Save changes"}
          </button>
          {dirty && (
            <span className="text-[13px] text-text-faint">Unsaved changes</span>
          )}
          {config && (
            <button
              type="button"
              onClick={() => setRemoveOpen(true)}
              className="ml-auto shrink-0 text-[13px] text-text-faint transition-colors hover:text-danger"
            >
              Remove gate
            </button>
          )}
        </div>
      </div>

      {/* evaluate — backed by POST /gates/{id}/evaluate, which runs the same
          FeatureGate.decide the select path uses. the board's latency readout
          is dropped (no endpoint exposes it) and the Last-24h panel with it. */}
      <div className="flex w-full shrink-0 flex-col gap-3 border-border-subtle px-[22px] py-5 xl:w-[380px] xl:border-l">
        <div className="flex flex-col gap-1">
          <span className="text-[15px] font-medium text-text-primary">Evaluate</span>
          <span className="text-[13px] leading-[1.5] text-text-dim">
            Run a sample context against the saved gate. Reads only — nothing is
            recorded and no traffic is affected.
          </span>
        </div>

        <textarea
          value={sample}
          onChange={(e) => setSample(e.target.value)}
          spellCheck={false}
          rows={7}
          className="w-full resize-y rounded-[10px] border border-border-subtle bg-bg-panel p-3 font-mono text-[12.5px] leading-[1.6] text-text-secondary outline-none focus:border-border-strong"
        />
        {sampleError && (
          <span className="text-[12.5px] text-danger">{sampleError}</span>
        )}

        <button
          type="button"
          onClick={runEvaluate}
          disabled={evaluate.isPending || !config}
          title={config ? undefined : "Save a gate first"}
          className="h-9 shrink-0 rounded-full bg-bg-hover px-4 text-[14px] font-medium text-text-primary transition-colors hover:bg-white/[0.09] disabled:opacity-40"
        >
          {evaluate.isPending ? "Evaluating…" : "Evaluate"}
        </button>

        {evaluation && <EvaluationResult result={evaluation} dirty={dirty} />}
      </div>

      <ConfirmDialog
        open={commitOpen}
        onClose={() => setCommitOpen(false)}
        tone="accent"
        title="Commit via feature gate"
        message={`Every eligible request will be served ${
          arms.find((a) => a.id === commitArm)?.name ?? "this variant"
        } and the learner will stop selecting. This changes live traffic immediately. The experiment keeps running and you can resume learning at any time.`}
        confirmLabel="Commit"
        loadingLabel="Committing…"
        loading={write.isPending}
        onConfirm={() =>
          write.mutate(
            { enabled: true, rollout_percentage: 0, default_arm_id: commitArm },
            {
              onSuccess: () => {
                setCommitOpen(false);
                setEnabled(true);
                setRollout(0);
                toast.success("Committed via feature gate");
              },
            },
          )
        }
      />

      <ConfirmDialog
        open={resumeOpen}
        onClose={() => setResumeOpen(false)}
        tone="accent"
        title="Resume learning"
        message={`Traffic returns to the learner and ${committedName} stops being forced. Nothing recorded the rollout this experiment had before it was committed, so choose what to resume at.`}
        confirmLabel="Resume"
        loadingLabel="Resuming…"
        loading={write.isPending}
        onConfirm={() =>
          write.mutate({ enabled: true, rollout_percentage: resumeRollout }, {
            onSuccess: () => {
              setResumeOpen(false);
              setRollout(resumeRollout);
              toast.success("Learning resumed");
            },
          })
        }
      >
        <label className="flex items-center justify-between gap-4 rounded-[10px] border border-border-subtle bg-bg-panel px-3 py-2.5">
          <span className="text-[13px] text-text-secondary">Resume at rollout</span>
          <span className="flex items-center gap-1.5">
            <input
              type="number"
              min={1}
              max={100}
              value={resumeRollout}
              onChange={(e) =>
                setResumeRollout(
                  Math.min(100, Math.max(1, Number(e.target.value) || 1)),
                )
              }
              className={cn(INPUT, "w-20 text-right")}
            />
            <span className="text-[13px] text-text-dim">%</span>
          </span>
        </label>
      </ConfirmDialog>

      {/* the one capability the retired /gates page owned */}
      <ConfirmDialog
        open={removeOpen}
        onClose={() => setRemoveOpen(false)}
        onConfirm={() => remove.mutate()}
        title="Delete Feature Gate"
        message="This will permanently remove the feature gate configuration. The experiment will continue to run without gate controls. This action cannot be undone."
        confirmLabel="Delete Gate"
        loadingLabel="Deleting…"
        loading={remove.isPending}
      />
    </div>
  );
}

const REASON: Record<GateEvaluateResponse["reason"], string> = {
  disabled: "Gate is disabled — the learner selects.",
  blackout: "Outside the active schedule.",
  rollout: "Outside the rollout.",
  rule: "A targeting rule matched.",
  bandit: "The learner selects.",
};

function EvaluationResult({
  result,
  dirty,
}: {
  result: GateEvaluateResponse;
  dirty: boolean;
}) {
  const good = result.eligible;

  return (
    <div className="flex flex-col gap-2.5 rounded-[12px] bg-bg-raised p-3.5">
      <div className="flex items-center gap-2">
        {good ? (
          <Check size={15} className="shrink-0 text-positive" />
        ) : (
          <Minus size={15} className="shrink-0 text-accent" />
        )}
        <span
          className={cn(
            "text-[14px] font-medium",
            good ? "text-positive" : "text-accent",
          )}
        >
          {good ? "Enters the experiment" : `Served ${result.arm_name ?? "the committed variant"}`}
        </span>
      </div>
      <p className="text-[12.5px] text-text-dim">{REASON[result.reason]}</p>

      <div className="flex flex-col gap-1.5 pt-0.5">
        {result.rules.map((r, i) => (
          <div key={i} className="flex items-center justify-between gap-3">
            <span className="min-w-0 truncate font-mono text-[12px] text-text-dim">
              {r.key} {r.operator} {String(r.value)}
            </span>
            <span
              className={cn(
                "shrink-0 font-mono text-[12px]",
                r.matched ? "text-positive" : "text-text-faint",
              )}
            >
              {r.matched ? (r.decisive ? "match ·" : "match") : "no match"}
            </span>
          </div>
        ))}
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-[12px] text-text-dim">rollout</span>
          <span
            className={cn(
              "font-mono text-[12px]",
              result.in_rollout ? "text-positive" : "text-text-faint",
            )}
          >
            {result.in_rollout ? "in" : "out of"} {result.rollout_percentage}%
          </span>
        </div>
      </div>

      {dirty && (
        <p className="border-t border-border-subtle pt-2.5 text-[12px] leading-[1.5] text-text-faint">
          Evaluated against the <em>saved</em> gate — your unsaved edits are not
          included.
        </p>
      )}
    </div>
  );
}
