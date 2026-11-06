import { apiFetch } from "./client";
import type { Connection, ConnectionDecision, ConnectionRequest } from "./types";

export const connections = {
  /** an admin gets every connection in the workspace; anyone else their own */
  async list(): Promise<Connection[]> {
    return (await apiFetch<{ connections: Connection[] }>("/v1/connections")).connections;
  },

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
