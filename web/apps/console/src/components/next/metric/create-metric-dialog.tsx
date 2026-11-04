"use client";

import { Button } from "@qbrix/ui/next/button";
import { Dialog } from "@qbrix/ui/next/dialog";
import { AgentPrompt } from "@qbrix/ui/next/empty";
import type { Metric } from "@/lib/api/types";
import { CREATE_METRIC } from "@/lib/metric/new-metric";
import { MetricFields, useMetricForm } from "./metric-form";

export function CreateMetricDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (metric: Metric) => void;
}) {
  const form = useMetricForm((metric) => {
    onCreated(metric);
    onClose();
  });

  const close = () => {
    form.reset();
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="New metric"
      dismissable={!form.pending}
      width={520}
      footer={
        <>
          <Button variant="quiet" disabled={form.pending} onClick={close}>
            Cancel
          </Button>
          <Button disabled={form.pending} onClick={form.submit}>
            {form.pending ? "Creating" : "Create metric"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <MetricFields form={form} />
        <div className="flex flex-col gap-2">
          <span className="n-meta font-medium text-n-text-3">Ask your agent</span>
          <AgentPrompt prompt={CREATE_METRIC} />
        </div>
      </div>
    </Dialog>
  );
}
