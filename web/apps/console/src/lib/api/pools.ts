import { apiFetch, buildQueryString } from "./client";
import type {
  Experiment,
  Pool,
  PoolCreateRequest,
  PoolUpdateRequest,
  PoolListResponse,
} from "./types";

export const pools = {
  async list(params?: { limit?: number; offset?: number }): Promise<PoolListResponse> {
    return apiFetch<PoolListResponse>(`/v1/pools${buildQueryString(params ?? {})}`);
  },

  async get(id: string): Promise<Pool> {
    return apiFetch<Pool>(`/v1/pools/${id}`);
  },

  async create(data: PoolCreateRequest): Promise<Pool> {
    return apiFetch<Pool>("/v1/pools", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async update(id: string, data: PoolUpdateRequest): Promise<Pool> {
    return apiFetch<Pool>(`/v1/pools/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async delete(id: string): Promise<void> {
    return apiFetch<void>(`/v1/pools/${id}`, { method: "DELETE" });
  },

  async listExperiments(poolId: string): Promise<Experiment[]> {
    return apiFetch<Experiment[]>(`/v1/pools/${poolId}/experiments`);
  },
};