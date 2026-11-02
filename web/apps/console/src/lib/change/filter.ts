export type ChangeWho = "member" | "connection" | "qbrix";

export type ChangeFilters = {
  who: ChangeWho | null;
  kind: string | null;
  loop: string | null;
  metric: string | null;
  undoable: boolean;
};

export const NO_FILTERS: ChangeFilters = { who: null, kind: null, loop: null, metric: null, undoable: false };

export const CHANGE_KINDS = [
  "loop.create",
  "loop.launch",
  "loop.rename",
  "loop.pause",
  "loop.resume",
  "loop.delete",
  "metric.create",
  "metric.delete",
];

export const WHO_WORDS: Record<ChangeWho, string> = {
  member: "people",
  connection: "agents",
  qbrix: "qbrix",
};

function isWho(value: string | null): value is ChangeWho {
  return value === "member" || value === "connection" || value === "qbrix";
}

export function parseFilters(params: Pick<URLSearchParams, "get">): ChangeFilters {
  const who = params.get("who");
  return {
    who: isWho(who) ? who : null,
    kind: params.get("kind") || null,
    loop: params.get("loop") || null,
    metric: params.get("metric") || null,
    undoable: params.get("undoable") === "true",
  };
}

export function filterParams({ who, kind, loop, metric, undoable }: ChangeFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (who) params.set("who", who);
  if (kind) params.set("kind", kind);
  if (loop) params.set("loop", loop);
  if (metric) params.set("metric", metric);
  if (undoable) params.set("undoable", "true");
  return params;
}

export function hasFilters(filters: ChangeFilters): boolean {
  return filterParams(filters).size > 0;
}

export function noneMatch(filters: ChangeFilters): string {
  const { who, kind, loop, metric, undoable } = filters;
  if (filterParams(filters).size > 1) return "No changes match these filters.";
  if (who) return `No changes by ${WHO_WORDS[who]}.`;
  if (kind) return `No ${kind} changes.`;
  if (loop) return `No changes to ${loop}.`;
  if (metric) return `No changes to ${metric}.`;
  if (undoable) return "Nothing here can be undone.";
  return "No changes yet.";
}
