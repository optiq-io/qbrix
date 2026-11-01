"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleDashed, Rocket } from "lucide-react";
import { Button } from "@qbrix/ui/next/button";
import { Consequence } from "@qbrix/ui/next/staged";
import { loops } from "@/lib/api/loops";
import { queryKeys } from "@/lib/api/query-keys";
import type { Loop, LoopResults } from "@/lib/api/types";
import { launchConsequence, readiness, type ReadyCheck } from "@/lib/loop/fact";

export function DraftOverview({
  loop,
  results,
  staging,
  onStagingEnd,
}: {
  loop: Loop;
  results: LoopResults | undefined;
  staging: boolean;
  onStagingEnd: () => void;
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
      {staging && <LaunchConsequence loop={loop} onEnd={onStagingEnd} />}
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

function LaunchConsequence({ loop, onEnd }: { loop: Loop; onEnd: () => void }) {
  const queryClient = useQueryClient();
  const panel = useRef<HTMLDivElement>(null);
  const { title, body } = launchConsequence(loop);

  useEffect(() => {
    panel.current?.focus();
    panel.current?.scrollIntoView({ block: "nearest" });
  }, []);

  const launch = useMutation({
    mutationFn: () => loops.launch(loop.key),
    onSuccess: (launched) => {
      queryClient.setQueryData(queryKeys.loops.detail(loop.key), launched);
      onEnd();
    },
    // not onError: that would replace the global toast a failed launch should show
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.loops.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.pins.all });
    },
  });

  return (
    <div ref={panel} tabIndex={-1} className="rounded-n-panel outline-none">
      <Consequence
        title={title}
        action={
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="secondary" disabled={launch.isPending} onClick={onEnd}>
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
      </Consequence>
    </div>
  );
}
