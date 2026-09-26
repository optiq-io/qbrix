"use client";

/**
 * the first-paint contract: a page names the queries it *is*, and is ready when
 * none of them is still waiting for its first answer.
 *
 * `isPending` and not `isLoading`: a query with a paused retry reports
 * `isLoading` false while holding no data, which would reveal an empty page
 * (the same distinction the first-run branch draws). a query that
 * has *errored* is ready — the page reveals and shows its error state, which is
 * content; holding the skeleton on a failed request is an infinite skeleton.
 *
 * a disabled query (`enabled: false` — an EE surface on a build without it) is
 * pending forever by react-query's reckoning and must not be counted.
 */
type ReadyLike = {
  isPending: boolean;
  isError: boolean;
  fetchStatus: "fetching" | "paused" | "idle";
};

export function usePageReady(queries: (ReadyLike | undefined)[]): boolean {
  return queries.every((q) => {
    if (!q) return true;
    if (!q.isPending) return true;
    if (q.isError) return true;
    // pending + idle = never asked, i.e. `enabled: false`
    return q.fetchStatus === "idle";
  });
}
