import { ApiError } from "../api/types";

const NOT_UNDOABLE = "CHANGE_NOT_UNDOABLE";

export type Refusal = { kind: "moved"; laterId: string } | { kind: "refused"; detail: string };

export function refusalOf(error: unknown): Refusal | null {
  if (!(error instanceof ApiError) || error.code !== NOT_UNDOABLE) return null;
  const laterId = error.context?.later_change_id;
  if (typeof laterId === "string") return { kind: "moved", laterId };
  return { kind: "refused", detail: error.detail };
}

/** the proxy's reasons are lowercase, for logs and agents */
export function asSentence(reason: string): string {
  const text = reason.charAt(0).toUpperCase() + reason.slice(1);
  return text.endsWith(".") ? text : `${text}.`;
}
