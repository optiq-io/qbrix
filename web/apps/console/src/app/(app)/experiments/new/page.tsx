"use client";

import { useSearchParams } from "next/navigation";
import { NewExperimentForm } from "@/components/experiments/new-experiment-form";
import { GuardedRoute } from "@/components/shell/mobile-guard";
import { routes } from "@/config/routes";

// `/experiments/new` is a static segment and wins over `/experiments/[id]`, so
// no experiment can shadow it — an id is a uuid and could never be "new" anyway.
//
// this does not reintroduce `/experiments` as a list: Home is the list, and that
// route stays retired. this is a leaf.

export default function NewExperimentPage() {
  const searchParams = useSearchParams();
  // the only context worth carrying in: arriving from a pool prefills it.
  // everything else the form asks for is a decision, not a context.
  const pool = searchParams.get("pool") ?? undefined;

  return (
    <GuardedRoute
      surface="experiment.new"
      backHref={routes.home}
      backLabel="Back to home"
    >
      <NewExperimentForm initialPoolId={pool} />
    </GuardedRoute>
  );
}
