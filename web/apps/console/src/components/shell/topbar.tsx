"use client";

import { Breadcrumb, useCrumbs, useCurrentExperiment } from "./breadcrumb";
import { PinToggle } from "./pinned";

// board `Console Shell` / Topbar — 62px on a hairline, 28px inset, crumb left
// and actions right. sticky rather than in-flow: the page keeps document
// scroll, so the crumb has to hold its place as content moves under it.
//
// below lg the 52px bar owns the route name instead, so this stays desktop-only.
//
// the board also draws a primary action here ("New experiment" on home, "New
// pool" on pools) while the page head beneath draws the same button again. that
// duplication is the boards', not a spec — each page decides which one
// survives, so nothing is moved here.
export function Topbar() {
  const crumbs = useCrumbs();
  const { id, experiment } = useCurrentExperiment();

  return (
    <div className="sticky top-0 z-30 hidden h-[62px] shrink-0 items-center justify-between gap-4 border-b border-border-subtle bg-bg px-7 lg:flex">
      <Breadcrumb crumbs={crumbs} />
      <div className="flex shrink-0 items-center gap-2">
        {id ? (
          <PinToggle experiment={{ id, name: experiment?.name ?? id }} />
        ) : null}
      </div>
    </div>
  );
}
