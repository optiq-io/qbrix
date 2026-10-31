import { apiFetch } from "./client";
import type { Pin, PinKind } from "./types";

function path(kind: PinKind, ref: string) {
  return `/v1/pins/${kind}/${encodeURIComponent(ref)}`;
}

export const pins = {
  async list(): Promise<Pin[]> {
    const { pins } = await apiFetch<{ pins: Pin[] }>("/v1/pins");
    return pins;
  },

  async pin(kind: PinKind, ref: string): Promise<void> {
    await apiFetch<void>(path(kind, ref), { method: "PUT" });
  },

  async unpin(kind: PinKind, ref: string): Promise<void> {
    await apiFetch<void>(path(kind, ref), { method: "DELETE" });
  },
};
