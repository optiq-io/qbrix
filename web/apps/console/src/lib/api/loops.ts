import { apiFetch } from "./client";
import type { ChangeEntry, Loop, LoopListPage, LoopResults, LoopResumed, ResultsRange } from "./types";

const RECENT_CHANGES = 50;
const LIST_PAGE = 200;
const PAUSES = 200;

function path(key: string) {
  return `/v1/loops/${encodeURIComponent(key)}`;
}

async function readChanges(params: URLSearchParams): Promise<ChangeEntry[]> {
  const { changes } = await apiFetch<{ changes: ChangeEntry[] }>(`/v1/changes?${params}`);
  return changes;
}

export const loops = {
  async list(cursor?: string): Promise<LoopListPage> {
    const params = new URLSearchParams({ limit: String(LIST_PAGE) });
    if (cursor) params.set("cursor", cursor);
    return apiFetch<LoopListPage>(`/v1/loops?${params}`);
  },

  async workspaceChanges(): Promise<ChangeEntry[]> {
    return readChanges(new URLSearchParams({ limit: String(RECENT_CHANGES) }));
  },

  /** unfolded, because a loop's newest pause says who paused it */
  async pauses(): Promise<ChangeEntry[]> {
    return readChanges(new URLSearchParams({ kind: "loop.pause", fold: "false", limit: String(PAUSES) }));
  },

  async get(key: string): Promise<Loop> {
    return apiFetch<Loop>(path(key));
  },

  async launch(key: string): Promise<Loop> {
    return apiFetch<Loop>(`${path(key)}/launch`, { method: "POST" });
  },

  async resume(key: string, reason?: string): Promise<LoopResumed> {
    return apiFetch<LoopResumed>(`${path(key)}/resume`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  async results(key: string, range: ResultsRange): Promise<LoopResults> {
    return apiFetch<LoopResults>(`${path(key)}/results?range=${range}`);
  },

  async changes(key: string): Promise<ChangeEntry[]> {
    return readChanges(new URLSearchParams({ loop: key, limit: String(RECENT_CHANGES) }));
  },
};
