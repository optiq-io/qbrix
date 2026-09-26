import { apiFetch } from "./client";
import type {
  GateConfigResponse,
  GateUpdateRequest,
  GateEvaluateRequest,
  GateEvaluateResponse,
} from "./types";

export const gates = {
  async getConfig(experimentId: string): Promise<GateConfigResponse> {
    return apiFetch<GateConfigResponse>(`/v1/gates/${experimentId}`);
  },

  async createConfig(experimentId: string, data: GateUpdateRequest): Promise<GateConfigResponse> {
    return apiFetch<GateConfigResponse>(`/v1/gates/${experimentId}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  // PATCH, not PUT: the board owns enabled/rollout/rules and nothing else, so a
  // save must not write back schedule, active hours or timezone it never showed.
  async updateConfig(experimentId: string, data: GateUpdateRequest): Promise<GateConfigResponse> {
    return apiFetch<GateConfigResponse>(`/v1/gates/${experimentId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  // dry-run: runs the same FeatureGate.decide the select path uses, so the
  // preview cannot drift from live behaviour. writes nothing.
  async evaluate(
    experimentId: string,
    data: GateEvaluateRequest
  ): Promise<GateEvaluateResponse> {
    return apiFetch<GateEvaluateResponse>(`/v1/gates/${experimentId}/evaluate`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async deleteConfig(experimentId: string): Promise<void> {
    return apiFetch<void>(`/v1/gates/${experimentId}`, {
      method: "DELETE",
    });
  },
};
