import { apiFetch } from "./client";
import type { ServiceHealthResponse, StreamLengthResponse } from "./types";

export const runtime = {
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
