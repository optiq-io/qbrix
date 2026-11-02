import { apiFetch } from "./client";
import type { CreateMetricBody, Metric } from "./types";

export const metrics = {
  async list(): Promise<Metric[]> {
    const { metrics: listed } = await apiFetch<{ metrics: Metric[] }>("/v1/metrics");
    return listed;
  },

  /** a new metric comes back without `loops`, because nothing can use it yet */
  async create(body: CreateMetricBody): Promise<Metric> {
    const created = await apiFetch<Omit<Metric, "loops">>("/v1/metrics", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return { ...created, loops: [] };
  },
};
