import { apiFetch, buildQueryString } from "./client";
import type { PoliciesListResponse } from "./types";

export const policies = {
  async list(params?: { reward_type?: string }): Promise<PoliciesListResponse> {
    return apiFetch<PoliciesListResponse>(`/v1/policies${buildQueryString(params ?? {})}`);
  },
};
