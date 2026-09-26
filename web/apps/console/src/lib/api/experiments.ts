import { apiFetch, buildQueryString } from "./client";
import type {
  Experiment,
  ExperimentCreateRequest,
  ExperimentUpdateRequest,
  ExperimentListResponse,
} from "./types";

export const experiments = {
  async list(params?: { limit?: number; offset?: number; search?: string; enabled?: boolean }): Promise<ExperimentListResponse> {
    return apiFetch<ExperimentListResponse>(`/v1/experiments${buildQueryString(params ?? {})}`);
  },

  async get(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`/v1/experiments/${id}`);
  },

  async create(data: ExperimentCreateRequest): Promise<Experiment> {
    return apiFetch<Experiment>("/v1/experiments", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async update(id: string, data: ExperimentUpdateRequest): Promise<Experiment> {
    return apiFetch<Experiment>(`/v1/experiments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  async delete(id: string): Promise<void> {
    return apiFetch<void>(`/v1/experiments/${id}`, { method: "DELETE" });
  },

  async reset(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`/v1/experiments/${id}/reset`, { method: "POST" });
  },
};
