"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleDashed, Rocket, Trash2 } from "lucide-react";
import { Button } from "@qbrix/ui/next/button";
import { routes } from "@/config/routes";
import { loops } from "@/lib/api/loops";
import { queryKeys } from "@/lib/api/query-keys";
import type { Loop, LoopResults } from "@/lib/api/types";
import { deleteConsequence, launchConsequence, readiness, type ReadyCheck } from "@/lib/loop/fact";
import { StagedPanel, type StagedAction } from "./staged-action";

export function DraftOverview({
  loop,
  results,
  staging,
  onCancel,
  onDone,
}: {
  loop: Loop;
  results: LoopResults | undefined;
  staging: StagedAction | null;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { checks, done, required } = readiness(loop, results);

  return (
    <div className="flex flex-col gap-5">
      <section className="overflow-hidden rounded-n-panel border border-n-line">
        <div className="flex items-center justify-between gap-2 border-b border-n-line-2 bg-n-bg px-4 py-3">
          <h2 className="n-body font-semibold text-n-text-1">Ready to launch</h2>
          <span className="n-label font-normal text-n-text-1">
            {done} of {required} required
          </span>
        </div>
        <ul>
          {checks.map((check) => (
            <Check key={check.label} check={check} />
          ))}
        </ul>
      </section>
      {staging === "launch" && <LaunchConsequence loop={loop} onCancel={onCancel} onDone={onDone} />}
      {staging === "delete" && <DeleteConsequence loop={loop} results={results} onCancel={onCancel} />}
    </div>
  );
}

function Check({ check }: { check: ReadyCheck }) {
  const Icon = check.done ? CircleCheck : CircleDashed;
  return (
    <li className="flex items-center gap-3 border-b border-n-line-2 px-4 py-3 last:border-b-0">
      <Icon size={16} className={check.done ? "shrink-0 text-n-ok-fg" : "shrink-0 text-n-text-3"} />
      <span className={`n-body w-[190px] shrink-0 font-medium ${check.optional ? "text-n-text-2" : "text-n-text-1"}`}>
        {check.label}
      </span>
      <span className="n-meta min-w-0 text-n-text-3">{check.detail}</span>
    </li>
  );
}

function LaunchConsequence({ loop, onCancel, onDone }: { loop: Loop; onCancel: () => void; onDone: () => void }) {
  const queryClient = useQueryClient();
  const { title, body } = launchConsequence(loop);

  const launch = useMutation({
    mutationFn: () => loops.launch(loop.key),
    onSuccess: (launched) => {
      queryClient.setQueryData(queryKeys.loops.detail(loop.key), launched);
      onDone();
    },
    // not onError: that would replace the global toast a failed launch should show
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.loops.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.pins.all });
    },
  });

  return (
    <StagedPanel
      title={title}
      action={
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" disabled={launch.isPending} onClick={onCancel}>
            Cancel
          </Button>
          <Button disabled={launch.isPending} onClick={() => launch.mutate()}>
            <Rocket size={13} />
            {launch.isPending ? "Launching" : "Launch"}
          </Button>
        </div>
      }
    >
      {body}
    </StagedPanel>
  );
}

function DeleteConsequence({
  loop,
  results,
  onCancel,
}: {
  loop: Loop;
  results: LoopResults | undefined;
  onCancel: () => void;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const deleted = useRef(false);
  const { title, body } = deleteConsequence(loop, results);

  // the page's own queries would read the deleted key as not found, so they go once it has left
  useEffect(
    () => () => {
      if (!deleted.current) return;
      for (const queryKey of [
        queryKeys.loops.detail(loop.key),
        ["loops", "results", loop.key],
        queryKeys.loops.changes(loop.key),
        queryKeys.loops.milestones(loop.key),
      ]) {
        queryClient.removeQueries({ queryKey });
      }
    },
    [queryClient, loop.key],
  );

  const remove = useMutation({
    mutationFn: () => loops.delete(loop.key),
    onSuccess: () => {
      deleted.current = true;
      for (const queryKey of [queryKeys.loops.list, queryKeys.loops.workspaceChanges, queryKeys.pins.all]) {
        queryClient.invalidateQueries({ queryKey });
      }
      router.replace(routes.next.home);
    },
    // not onError: that would replace the global toast a refused delete should show
    onSettled: (_data, error) => {
      if (error) queryClient.invalidateQueries({ queryKey: queryKeys.loops.detail(loop.key) });
    },
  });

  return (
    <StagedPanel
      title={title}
      action={
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" disabled={remove.isPending || remove.isSuccess} onClick={onCancel}>
            Keep draft
          </Button>
          <Button variant="danger" disabled={remove.isPending || remove.isSuccess} onClick={() => remove.mutate()}>
            <Trash2 size={13} />
            {remove.isPending || remove.isSuccess ? "Deleting" : "Delete draft"}
          </Button>
        </div>
      }
    >
      {body}
    </StagedPanel>
  );
}
