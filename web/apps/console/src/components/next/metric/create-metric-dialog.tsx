"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@qbrix/ui/next/button";
import { Dialog } from "@qbrix/ui/next/dialog";
import { AgentPrompt } from "@qbrix/ui/next/empty";
import { MonoField, TextField } from "@qbrix/ui/next/field";
import { metrics } from "@/lib/api/metrics";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError, type Metric } from "@/lib/api/types";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { windowLabel } from "@/lib/loop/fact";
import {
  METRIC_TYPES,
  metricErrorField,
  NEW_METRIC,
  parseWindow,
  validateMetric,
  type MetricDraft,
  type MetricErrors,
  type MetricField,
} from "@/lib/metric/new-metric";

const AGENT_PROMPT = "Create an order value metric, 7 days";

export function CreateMetricDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (metric: Metric) => void;
}) {
  const queryClient = useQueryClient();
  const showError = useApiErrorToast();
  const [draft, setDraft] = useState<MetricDraft>(NEW_METRIC);
  const [errors, setErrors] = useState<MetricErrors>({});

  const close = () => {
    setDraft(NEW_METRIC);
    setErrors({});
    onClose();
  };

  const create = useMutation({
    mutationFn: metrics.create,
    onSuccess: (metric) => {
      queryClient.setQueryData<Metric[]>(queryKeys.metrics.list, (listed) => [...(listed ?? []), metric]);
      queryClient.invalidateQueries({ queryKey: queryKeys.metrics.all });
      onCreated(metric);
      close();
    },
    onError: (error) => {
      const placed = error instanceof ApiError ? metricErrorField(error) : null;
      if (placed) setErrors((current) => ({ ...current, [placed.field]: placed.message }));
      else showError(error);
    },
  });

  const edit = (patch: Partial<MetricDraft>, field?: MetricField) => {
    setDraft((current) => ({ ...current, ...patch }));
    if (field) setErrors(({ [field]: _, ...rest }) => rest);
  };

  const submit = () => {
    const checked = validateMetric(draft);
    if (checked.errors) setErrors(checked.errors);
    else create.mutate(checked.body);
  };

  const seconds = parseWindow(draft.window);

  return (
    <Dialog
      open={open}
      onClose={close}
      title="New metric"
      dismissable={!create.isPending}
      width={520}
      footer={
        <>
          <Button variant="quiet" disabled={create.isPending} onClick={close}>
            Cancel
          </Button>
          <Button disabled={create.isPending} onClick={submit}>
            {create.isPending ? "Creating" : "Create metric"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <MonoField
          label="Name"
          hint="What track and outcome send as the metric."
          placeholder="order_value"
          value={draft.name}
          error={errors.name}
          onChange={(event) => edit({ name: event.target.value }, "name")}
        />
        <TextField
          label="Semantic"
          hint="One sentence on what it stands for. Agents read it; when the code changes it, a new version records why."
          placeholder="Total paid for the order, in euros"
          value={draft.semantic}
          error={errors.semantic}
          onChange={(event) => edit({ semantic: event.target.value }, "semantic")}
        />
        <fieldset className="flex flex-col gap-1.5">
          <legend className="n-meta mb-1.5 font-medium text-n-text-3">Type</legend>
          <div className="flex flex-col gap-1">
            {METRIC_TYPES.map((type) => (
              <label
                key={type.value}
                className={`flex cursor-pointer items-start gap-2 rounded-n-control border p-2 ${
                  draft.type === type.value ? "border-n-text-1" : "border-n-line hover:bg-n-fill-1"
                }`}
              >
                <input
                  type="radio"
                  name="metric-type"
                  value={type.value}
                  checked={draft.type === type.value}
                  onChange={() => edit({ type: type.value }, "range")}
                  className="mt-[3px] accent-[var(--n-ink)]"
                />
                <span className="flex min-w-0 flex-col">
                  <span className="n-body text-n-text-1">{type.label}</span>
                  <span className="n-meta text-n-text-2">{type.description}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {draft.type === "score" && (
          <div className="flex flex-col gap-1.5">
            <div className="grid grid-cols-2 gap-2">
              <TextField
                label="Lowest"
                inputMode="decimal"
                placeholder="1"
                value={draft.lo}
                aria-invalid={errors.range ? true : undefined}
                onChange={(event) => edit({ lo: event.target.value }, "range")}
              />
              <TextField
                label="Highest"
                inputMode="decimal"
                placeholder="5"
                value={draft.hi}
                aria-invalid={errors.range ? true : undefined}
                onChange={(event) => edit({ hi: event.target.value }, "range")}
              />
            </div>
            {errors.range && <p className="n-label font-normal text-n-no-fg">{errors.range}</p>}
          </div>
        )}
        <TextField
          label="Window"
          hint="How long a decision waits for its outcome. Outcomes after it are recorded as late and teach nothing."
          value={draft.window}
          error={errors.window}
          onChange={(event) => edit({ window: event.target.value }, "window")}
        />
        {seconds !== null && (
          <p className="n-meta rounded-n-control bg-n-fill-1 px-3 py-2 text-n-text-2">
            A decision with no outcome after {windowLabel(seconds)} is sealed with 0. You never send zeros.
          </p>
        )}
        <div className="flex flex-col gap-2">
          <span className="n-meta font-medium text-n-text-3">Ask your agent</span>
          <AgentPrompt prompt={AGENT_PROMPT} />
        </div>
      </div>
    </Dialog>
  );
}
