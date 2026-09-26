"use client";

import Link from "next/link";
import { Check, Plus } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { routes } from "@/config/routes";

// board `APP · First run · empty console` / Quick start.
//
// steps 1 and 2 always complete together: a pool's variants are fixed at
// creation and there is no add-variant endpoint, so one action satisfies both.
// step 2 is left in as confirmation the variants are in, and never carries a
// cta.
//
// the one cta is "New experiment", not "New pool": the form writes the pool
// inline, so the create-a-pool-first prerequisite this list used to describe no
// longer exists. the steps still name the pool because it is still a real thing
// that gets made — just not a separate errand.

const STEPS = [
  {
    title: "Name a pool",
    body: "A pool holds the variants you want qbrix to choose between. You write it inside the experiment form.",
  },
  {
    title: "Add your variants",
    body: "Two or more. Give each one a name your code can switch on.",
  },
  {
    title: "Start an experiment",
    body: "A reward type and a strategy. Auto is the right default — it runs several and keeps the one that learns fastest.",
  },
  {
    title: "Call select() and report feedback",
    body: "One call to choose, one call to tell qbrix what happened.",
  },
];

export function QuickStart({
  done,
}: {
  /** one flag per step, in order */
  done: boolean[];
}) {
  const completed = done.filter(Boolean).length;
  const active = done.findIndex((d) => !d);

  return (
    <div className="flex flex-col overflow-hidden rounded-[12px] border border-border-subtle bg-bg-raised">
      <div className="flex items-center justify-between gap-4 border-b border-border-subtle px-[18px] py-3.5">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.086em] text-text-faint">
          Quick start
        </span>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10.5px] text-text-dim">
            {completed} of {STEPS.length}
          </span>
          <span className="h-1 w-[70px] overflow-hidden rounded-full bg-bar">
            <span
              className="block h-1 rounded-full bg-accent transition-all"
              style={{
                width: `${Math.max((completed / STEPS.length) * 100, completed > 0 ? 8 : 3)}%`,
              }}
            />
          </span>
        </div>
      </div>

      {STEPS.map((step, i) => {
        const isDone = done[i];
        const isActive = i === active;
        return (
          <div
            key={step.title}
            className={cn(
              "flex gap-3.5 px-[18px] py-4",
              i > 0 && "border-t border-border-subtle",
              isActive && "bg-accent/[0.024]",
            )}
          >
            <span
              className={cn(
                "mt-px flex size-[22px] shrink-0 items-center justify-center rounded-full border font-mono text-[11px]",
                isDone && "border-accent bg-accent-soft text-accent",
                isActive && "border-accent bg-accent text-bg",
                !isDone && !isActive && "border-border text-text-faint",
              )}
            >
              {isDone ? <Check size={12} /> : i + 1}
            </span>

            <div className="flex min-w-0 flex-1 flex-col gap-[5px]">
              <span
                className={cn(
                  "text-[14.5px] font-semibold tracking-[-0.28px]",
                  isDone ? "text-text-dim" : "text-text-primary",
                )}
              >
                {step.title}
              </span>
              <span className="text-[13px] leading-[1.5] text-text-dim">
                {step.body}
              </span>
            </div>

            {isActive && i === 0 && (
              <Link
                href={routes.newExperiment()}
                className="flex h-8 shrink-0 items-center gap-1.5 self-start rounded-lg bg-accent px-3 text-[13px] font-semibold text-bg transition-colors hover:bg-accent/90"
              >
                <Plus size={14} />
                New experiment
              </Link>
            )}
          </div>
        );
      })}
    </div>
  );
}
