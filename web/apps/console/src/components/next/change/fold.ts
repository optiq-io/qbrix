"use client";

import { useQueries } from "@tanstack/react-query";
import { changes } from "@/lib/api/changes";
import { queryKeys } from "@/lib/api/query-keys";
import type { ChangeEntry } from "@/lib/api/types";

export type ChangeRow = { key: string; entry: ChangeEntry; foldKey?: string };

/** a row's fold shares its newest change's id, so its rows need keys of their own */
function childKey(fold: ChangeEntry, id: string) {
  return `${fold.id}/${id}`;
}

/** the changes in each open fold, by id: the list can't start at a fold's place, while ids is exact */
export function useChangeRows(entries: ChangeEntry[], open: Set<string>): ChangeRow[] {
  const folds = entries.filter((entry) => entry.count > 1 && open.has(entry.id));
  const loaded = useQueries({
    queries: folds.map((fold) => ({
      queryKey: queryKeys.changes.fold(fold.ids),
      queryFn: () => Promise.all(fold.ids.map(changes.get)),
    })),
  });
  const inside = new Map(folds.map((fold, at) => [fold.id, loaded[at].data ?? []]));

  return entries.flatMap((entry): ChangeRow[] => [
    { key: entry.id, entry },
    ...(inside.get(entry.id) ?? []).map((child) => ({
      key: childKey(entry, child.id),
      entry: child,
      foldKey: entry.id,
    })),
  ]);
}
