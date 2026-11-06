import { apiFetch } from "./client";
import type { ServiceHealthResponse, StreamLengthResponse, WorkspaceStatus } from "./types";

export const runtime = {
  async status(): Promise<WorkspaceStatus> {
    return apiFetch<WorkspaceStatus>("/v1/runtime/status");
  },

  async redisHealth(): Promise<ServiceHealthResponse> {
    return apiFetch<ServiceHealthResponse>("/v1/runtime/redis/health");
  },

  async motorHealth(): Promise<ServiceHealthResponse> {
    return apiFetch<ServiceHealthResponse>("/v1/runtime/motor/health");
  },

  async cortexHealth(): Promise<ServiceHealthResponse> {
    return apiFetch<ServiceHealthResponse>("/v1/runtime/cortex/health");
  },

  async streamSize(): Promise<StreamLengthResponse> {
    return apiFetch<StreamLengthResponse>("/v1/runtime/redis/stream/size");
  },
};
