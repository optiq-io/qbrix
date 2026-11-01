import { apiFetch } from "./client";
import type { ChangeEntry, Loop, LoopResults, ResultsRange } from "./types";

const RECENT_CHANGES = 50;

function path(key: string) {
  return `/v1/loops/${encodeURIComponent(key)}`;
}

export const loops = {
  async get(key: string): Promise<Loop> {
    return apiFetch<Loop>(path(key));
  },

  async launch(key: string): Promise<Loop> {
    return apiFetch<Loop>(`${path(key)}/launch`, { method: "POST" });
  },

  async results(key: string, range: ResultsRange): Promise<LoopResults> {
    return apiFetch<LoopResults>(`${path(key)}/results?range=${range}`);
  },

  async changes(key: string): Promise<ChangeEntry[]> {
    const params = new URLSearchParams({ loop: key, limit: String(RECENT_CHANGES) });
    const { changes } = await apiFetch<{ changes: ChangeEntry[] }>(`/v1/changes?${params}`);
    return changes;
  },
};
