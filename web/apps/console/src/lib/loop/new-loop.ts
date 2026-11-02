import type { CreateLoopBody } from "@/lib/api/types";

export const START_LOOP = "Start a loop for the checkout headline";

const KEY = /^[a-z0-9][a-z0-9_.-]*$/;
const KEY_MAX_LENGTH = 64;
const GENERATED_MAX_LENGTH = KEY_MAX_LENGTH - "-999".length;
const RESERVED_LOOP_KEY = "new";
const KEY_RULE = "Use lowercase letters, digits, _, - and ., starting with a letter or digit, at most 64 characters.";

export type OptionRow = {
  id: string;
  name: string;
  /** null follows the name */
  key: string | null;
  config: string;
};

export type LoopDraft = {
  name: string;
  /** null follows the name */
  key: string | null;
  purpose: string;
  options: OptionRow[];
  /** a row's id; null is the first filled row */
  fallback: string | null;
  metric: string | null;
};

export type RowErrors = { name?: string; key?: string; config?: string };

export type DraftErrors = {
  name?: string;
  key?: string;
  metric?: string;
  options?: string;
  rows?: Record<string, RowErrors>;
};

export function isKey(value: string): boolean {
  return value.length <= KEY_MAX_LENGTH && KEY.test(value);
}

/** the server's rule for a key left out, so what the form shows is what it sends */
export function keyFrom(name: string, whenEmpty: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug.slice(0, GENERATED_MAX_LENGTH).replace(/-+$/, "") || whenEmpty;
}

export function loopKey(draft: Pick<LoopDraft, "name" | "key">): string {
  if (draft.key !== null) return draft.key;
  if (!draft.name.trim()) return "";
  const key = keyFrom(draft.name, "loop");
  return key === RESERVED_LOOP_KEY ? `${key}-2` : key;
}

function isFilled(row: OptionRow): boolean {
  return Boolean(row.name.trim() || row.key !== null || row.config.trim());
}

/** given keys are taken first, then generated ones in row order, as the server does */
export function optionKeys(rows: OptionRow[]): Map<string, string> {
  const taken = new Set(rows.flatMap((row) => (row.key === null ? [] : [row.key])));
  const keys = new Map<string, string>();
  for (const row of rows) {
    if (row.key !== null) {
      keys.set(row.id, row.key);
      continue;
    }
    if (!row.name.trim()) {
      keys.set(row.id, "");
      continue;
    }
    const base = keyFrom(row.name, "option");
    let key = base;
    for (let n = 2; taken.has(key); n += 1) key = `${base}-${n}`;
    taken.add(key);
    keys.set(row.id, key);
  }
  return keys;
}

export function fallbackRow(draft: Pick<LoopDraft, "options" | "fallback">): OptionRow | undefined {
  const filled = draft.options.filter(isFilled);
  return filled.find((row) => row.id === draft.fallback) ?? filled[0];
}

function parseConfig(text: string): Record<string, unknown> | null {
  if (!text.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export type ValidatedDraft = { errors: DraftErrors; body?: undefined } | { errors?: undefined; body: CreateLoopBody };

export function validateDraft(draft: LoopDraft): ValidatedDraft {
  const errors: DraftErrors = {};
  const key = loopKey(draft);

  if (!draft.name.trim()) errors.name = "A loop needs a name.";
  if (key === RESERVED_LOOP_KEY) errors.key = "qbrix uses this key. Choose another.";
  else if (key && !isKey(key)) errors.key = KEY_RULE;
  if (!draft.metric) errors.metric = "Choose the metric this loop learns from.";

  const filled = draft.options.filter(isFilled);
  if (filled.length < 2) errors.options = "A loop needs at least two options.";

  const keys = optionKeys(filled);
  const seen = new Set<string>();
  const rows: Record<string, RowErrors> = {};
  const options: CreateLoopBody["options"] = [];
  for (const row of filled) {
    const rowErrors: RowErrors = {};
    const rowKey = keys.get(row.id) ?? "";
    const config = parseConfig(row.config);
    if (!row.name.trim()) rowErrors.name = "Every option needs a name.";
    if (rowKey && !isKey(rowKey)) rowErrors.key = KEY_RULE;
    else if (rowKey && seen.has(rowKey)) rowErrors.key = "Two options have this key.";
    if (config === null) rowErrors.config = 'Use a JSON object, like { "headline": "Pay in one tap" }.';
    seen.add(rowKey);
    if (Object.keys(rowErrors).length > 0) rows[row.id] = rowErrors;
    else if (config) options.push({ name: row.name.trim(), key: rowKey, config });
  }
  if (Object.keys(rows).length > 0) errors.rows = rows;

  if (Object.keys(errors).length > 0) return { errors };

  const fallback = fallbackRow(draft);
  return {
    body: {
      name: draft.name.trim(),
      key,
      purpose: draft.purpose.trim(),
      metric: draft.metric as string,
      options,
      fallback: keys.get(fallback?.id ?? "") ?? "",
    },
  };
}

export function createConsequence(draft: LoopDraft): string {
  const key = loopKey(draft);
  const fallback = fallbackRow(draft)?.name.trim();
  const creates = key ? `Creates ${key} as a draft.` : "Creates a draft.";
  return `${creates} Your app gets the fallback${fallback ? `, ${fallback},` : ""} until you launch it.`;
}

export function fallbackNote(draft: Pick<LoopDraft, "options" | "fallback">): string {
  const fallback = fallbackRow(draft);
  const first = draft.options.find(isFilled);
  const subject = fallback && fallback.id !== first?.id && fallback.name.trim() ? fallback.name.trim() : "The first option";
  return `${subject} is the fallback: what your app gets while the loop is a draft or paused. Launching starts cycle 1 at an even split.`;
}

function sentence(detail: string): string {
  return `${detail.charAt(0).toUpperCase()}${detail.slice(1)}.`;
}

export type LoopErrorField = "name" | "key" | "metric" | "options";

/** where the server's refusal belongs on the form; null when no field can fix it */
export function loopErrorField(error: {
  code?: string;
  detail: string;
}): { field: LoopErrorField; message: string } | null {
  if (error.code === "LOOP_KEY_TAKEN") return { field: "key", message: "Another loop already has this key." };
  if (error.code !== "INVALID_LOOP") return null;
  const { detail } = error;
  const message = sentence(detail);
  if (/^a loop (key|can't have the key)/.test(detail)) return { field: "key", message };
  if (/^(no metric|a loop needs a metric)/.test(detail)) return { field: "metric", message };
  if (detail.startsWith("a loop needs a name")) return { field: "name", message };
  if (/option|fallback/.test(detail)) return { field: "options", message };
  return null;
}
