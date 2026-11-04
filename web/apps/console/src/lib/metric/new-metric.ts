import type { CreateMetricBody, Metric, MetricType } from "@/lib/api/types";
import { isKey } from "../loop/new-loop";

export const CREATE_METRIC = "Create an order value metric, 7 days";

export const METRIC_TYPES: { value: MetricType; label: string; description: string }[] = [
  { value: "conversion", label: "Conversion", description: "Did it happen: 0 or 1. The first outcome counts." },
  { value: "count", label: "Count", description: "How many times. Outcomes add up." },
  { value: "value", label: "Value", description: "How much, such as revenue. Outcomes add up." },
  { value: "score", label: "Score", description: "A rating on a range you set. The last one counts." },
];

export function metricTypeLabel(type: MetricType): string {
  return METRIC_TYPES.find((option) => option.value === type)?.label ?? type;
}

export function usedBy(metric: Pick<Metric, "loops">): string {
  const { loops } = metric;
  if (loops.length === 0) return "no other loop yet";
  if (loops.length === 1) return loops[0].name;
  return `${loops.length} other loops`;
}

const UNIT_SECONDS: Record<string, number> = {
  s: 1,
  sec: 1,
  second: 1,
  m: 60,
  min: 60,
  minute: 60,
  h: 3_600,
  hr: 3_600,
  hour: 3_600,
  d: 86_400,
  day: 86_400,
  w: 604_800,
  week: 604_800,
};

/** "7 days" as seconds; null for anything else */
export function parseWindow(text: string): number | null {
  const match = /^(\d+)\s*([a-z]+?)s?$/.exec(text.trim().toLowerCase());
  if (!match) return null;
  const unit = UNIT_SECONDS[match[2]];
  const amount = Number(match[1]);
  return unit && amount > 0 ? amount * unit : null;
}

export type MetricDraft = {
  name: string;
  semantic: string;
  type: MetricType;
  window: string;
  lo: string;
  hi: string;
};

export type MetricField = "name" | "semantic" | "window" | "range";
export type MetricErrors = Partial<Record<MetricField, string>>;

export const NEW_METRIC: MetricDraft = { name: "", semantic: "", type: "conversion", window: "24 hours", lo: "", hi: "" };

function score(draft: MetricDraft): { lo: number; hi: number } | null {
  if (!draft.lo.trim() || !draft.hi.trim()) return null;
  const range = { lo: Number(draft.lo), hi: Number(draft.hi) };
  return Number.isFinite(range.lo) && Number.isFinite(range.hi) && range.lo < range.hi ? range : null;
}

export function validateMetric(draft: MetricDraft): { errors: MetricErrors; body?: undefined } | { errors?: undefined; body: CreateMetricBody } {
  const errors: MetricErrors = {};
  const name = draft.name.trim();
  const semantic = draft.semantic.trim();
  const windowSeconds = parseWindow(draft.window);
  const range = draft.type === "score" ? score(draft) : null;

  if (!name) errors.name = "A metric needs a name.";
  else if (!isKey(name)) errors.name = "Use lowercase letters, digits, _, - and ., starting with a letter or digit, at most 64 characters.";
  if (!semantic) errors.semantic = "Say in one sentence what it stands for.";
  if (windowSeconds === null) errors.window = "Use an amount and a unit, like 24 hours or 7 days.";
  if (draft.type === "score" && !range) errors.range = "A score needs a lowest and a highest value, lowest first.";

  if (Object.keys(errors).length > 0) return { errors };
  return { body: { name, semantic, type: draft.type, range, window_seconds: windowSeconds as number } };
}

/** where the server's refusal belongs on the form; null when no field can fix it */
export function metricErrorField(error: {
  code?: string;
  detail: string;
}): { field: MetricField; message: string } | null {
  if (error.code === "METRIC_NAME_TAKEN") return { field: "name", message: "A metric already has this name." };
  if (error.code !== "INVALID_METRIC") return null;
  const { detail } = error;
  const message = `${detail.charAt(0).toUpperCase()}${detail.slice(1)}.`;
  if (detail.startsWith("a metric name")) return { field: "name", message };
  if (detail.includes("semantic")) return { field: "semantic", message };
  if (detail.includes("window")) return { field: "window", message };
  if (detail.includes("range")) return { field: "range", message };
  return null;
}
