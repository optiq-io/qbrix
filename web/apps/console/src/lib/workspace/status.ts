import type { WorkspaceStatus } from "@/lib/api/types";
import { span } from "../loop/fact";

export function statusProblem(status: WorkspaceStatus): string | null {
  if (!status.services.storage) return "Storage isn't answering";
  if (!status.services.deciding) return "Deciding isn't answering";
  if (!status.services.learning) return "Learning isn't answering";
  if (!status.learning.behind) return null;
  if (status.learning.lag_ms === null) return "Learning is behind";
  return `Learning is ${span(status.learning.lag_ms / 1000)} behind`;
}
