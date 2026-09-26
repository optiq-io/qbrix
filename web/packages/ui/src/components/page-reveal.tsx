"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "../lib/utils";

interface PageRevealProps {
  /** true once every query in the page's first-paint set has settled */
  ready: boolean;
  /** the page's own shape, at the geometry its content will occupy */
  skeleton: React.ReactNode;
  children: React.ReactNode;
  /** applied to the revealed root — PageReveal *is* the page root, so a page
      laid out with flex passes its own `flex flex-1 flex-col` through here */
  className?: string;
}

/**
 * holds a page at its skeleton until its first-paint set has landed, then
 * commits the whole page in one frame.
 *
 * the failure this exists for: a page of N independent queries reveals N times.
 * every region arrives on its own clock, rows fill column by column, and any
 * element that animates on data change stages that animation once per load —
 * which on Home meant every allocation bar performing a fake reallocation
 * before it had ever seen an allocation.
 *
 * what belongs in the first-paint set is what the page *is*. polling and
 * secondary data — activity, stream depth, service health — stay out of it and
 * update in place; gating the page on a 30s poll would hold it hostage to the
 * slowest thing on it.
 *
 * what this wraps is the page's data region, not always the whole page. board
 * `APP · Empty, loading & error states` keeps the panel's own label ("EXPERIMENTS")
 * drawn while its rows are skeletons, so a head that owes nothing to a request —
 * Pools' title and its fixed description — renders immediately and sits outside.
 * a head that is itself data — Home's greeting and its running/pool counts —
 * goes inside, because "—" and then a value is the same two-stage arrival in a
 * smaller box.
 */
export function PageReveal({
  ready,
  skeleton,
  children,
  className,
}: PageRevealProps) {
  // sticky. a page reveals once and never returns to the skeleton: a search, a
  // filter, a poll and a refetch all put queries back into pending, and
  // blanking the page for each is the same jump the reveal removes.
  const [revealed, setRevealed] = useState(ready);

  // a page whose data was already cached must appear instantly, with no fade.
  // the fade covers a wait; where there was no wait it is just a flicker on
  // every navigation.
  const instant = useRef(ready);

  useEffect(() => {
    if (ready) setRevealed(true);
  }, [ready]);

  if (!revealed) return <>{skeleton}</>;

  return (
    <div className={cn(!instant.current && "page-reveal", className)}>
      {children}
    </div>
  );
}

/**
 * the allocation bar while its data is still in flight.
 *
 * it cannot be an equal-split version of itself: a uniform split is a specific
 * and wrong claim about a bandit, and animating out of it reads as the learner
 * shifting weight.
 */
export function SkeletonTrack({
  className,
  height = 9,
}: {
  className?: string;
  height?: number;
}) {
  return (
    <div
      className={cn("w-full animate-pulse rounded-[4px] bg-border/40", className)}
      style={{ height }}
    />
  );
}

/**
 * the same rail once the answer is in and the answer is "nothing yet".
 *
 * identical geometry, deliberately not `animate-pulse`: an experiment that has
 * served no traffic is a settled fact, and a pulsing bar would tell you its
 * allocation is still loading for as long as the page is open.
 */
export function EmptyTrack({
  className,
  height = 9,
}: {
  className?: string;
  height?: number;
}) {
  return (
    <div
      className={cn("w-full rounded-[4px] bg-border/25", className)}
      style={{ height }}
    />
  );
}
