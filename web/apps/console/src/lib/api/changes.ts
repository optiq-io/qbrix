import { filterParams, type ChangeFilters } from "@/lib/change/filter";
import { apiFetch } from "./client";
import type { ChangeCounts, ChangeEntry, ChangePage } from "./types";

const PAGE = 50;

export const changes = {
  async list(filters: ChangeFilters, cursor?: string): Promise<ChangePage> {
    const params = filterParams(filters);
    params.set("limit", String(PAGE));
    if (cursor) params.set("cursor", cursor);
    return apiFetch<ChangePage>(`/v1/changes?${params}`);
  },

  async counts(filters: ChangeFilters): Promise<ChangeCounts> {
    return apiFetch<ChangeCounts>(`/v1/changes/counts?${filterParams(filters)}`);
  },

  async get(id: string): Promise<ChangeEntry> {
    return apiFetch<ChangeEntry>(`/v1/changes/${encodeURIComponent(id)}`);
  },

  async undo(id: string, reason?: string): Promise<ChangeEntry> {
    return apiFetch<ChangeEntry>(`/v1/changes/${encodeURIComponent(id)}/undo`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },
};
