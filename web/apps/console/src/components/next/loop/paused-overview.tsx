"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useToast } from "@qbrix/ui/components/toast";
import { Button } from "@qbrix/ui/next/button";
import { TextArea } from "@qbrix/ui/next/field";
import { loops } from "@/lib/api/loops";
import { queryKeys } from "@/lib/api/query-keys";
import { ApiError, type Loop, type LoopResults } from "@/lib/api/types";
import { useApiErrorToast } from "@/lib/api/use-api-error-toast";
import { fallbackName } from "@/lib/loop/fact";
import { pauseRows, resumeConsequence, type Pause } from "@/lib/loop/pause";
import { StagedPanel } from "./staged-action";

const NOT_PAUSED = "LOOP_NOT_PAUSED";

export function PausedOverview({
  loop,
  pause,
  results,
  now,
  staging,
  onCancel,
  onDone,
}: {
  loop: Loop;
  pause: Pause | null;
  results: LoopResults | undefined;
  now: number;
  staging: boolean;
  onCancel: () => void;
  onDone: () => void;
}) {
  const rows = pauseRows(pause, fallbackName(loop), results);

  return (
    <div className="flex flex-col gap-5">
      {rows.length > 0 && (
        <dl className="flex flex-wrap gap-x-8 gap-y-3 rounded-n-panel border border-n-line px-4 py-3">
          {rows.map(({ label, value }) => (
            <div key={label} className="flex min-w-0 flex-col gap-1">
              <dt className="n-label font-normal text-n-text-3">{label}</dt>
              <dd className="n-meta text-n-text-1">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {staging && <ResumeConsequence loop={loop} pause={pause} now={now} onCancel={onCancel} onDone={onDone} />}
    </div>
  );
}

function ResumeConsequence({
  loop,
  pause,
  now,
  onCancel,
  onDone,
}: {
  loop: Loop;
  pause: Pause | null;
  now: number;
  onCancel: () => void;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const showError = useApiErrorToast();
  const [reason, setReason] = useState("");
  const { title, body } = resumeConsequence(loop.cycle?.number, pause, now);

  const resume = useMutation({
    mutationFn: () => loops.resume(loop.key, reason.trim() || undefined),
    onSuccess: ({ loop: resumed, serving_within_seconds: seconds }) => {
      queryClient.setQueryData(queryKeys.loops.detail(loop.key), resumed);
      toast.success(`Serving the engine's choices again within ${seconds} s`);
      onDone();
    },
    // replaces the global toast, so anything but a lost race has to show it itself
    onError: (error) => {
      if (error instanceof ApiError && error.code === NOT_PAUSED) onDone();
      else showError(error);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.loops.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.pins.all });
    },
  });

  return (
    <StagedPanel
      title={title}
      field={
        <TextArea
          label="Reason, optional"
          rows={2}
          value={reason}
          disabled={resume.isPending}
          onChange={(event) => setReason(event.target.value)}
        />
      }
      action={
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" disabled={resume.isPending} onClick={onCancel}>
            Keep paused
          </Button>
          <Button disabled={resume.isPending} onClick={() => resume.mutate()}>
            <Play size={13} />
            {resume.isPending ? "Resuming" : "Resume"}
          </Button>
        </div>
      }
    >
      {body}
    </StagedPanel>
  );
}
