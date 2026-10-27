import { apiFetch } from "./client";
import type { ConnectionDecision, ConnectionRequest } from "./types";

export const connections = {
  async getRequest(id: string): Promise<ConnectionRequest> {
    return apiFetch<ConnectionRequest>(`/v1/connections/requests/${encodeURIComponent(id)}`);
  },

  async decide(id: string, approve: boolean): Promise<ConnectionDecision> {
    return apiFetch<ConnectionDecision>(`/v1/connections/requests/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ approve }),
    });
  },
};
