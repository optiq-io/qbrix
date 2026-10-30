import { captionFor, type StatusRow } from "./status";

/** a raw value already formatted, or one with the caption only the page knows: "since 03:12" */
export type FactValue = string | { value: string; caption: string };

export type Fact = { key: string; label: string; value: string; caption?: string };

export function facts(row: Pick<StatusRow, "facts">, values: Record<string, FactValue | undefined>): Fact[] {
  return row.facts.map(({ key, label, caption }) => {
    const entry = values[key];
    if (typeof entry === "object") return { key, label, value: entry.value, caption: entry.caption };
    const value = entry ?? "—";
    return { key, label, value, caption: caption === undefined ? undefined : captionFor(caption, value) };
  });
}
