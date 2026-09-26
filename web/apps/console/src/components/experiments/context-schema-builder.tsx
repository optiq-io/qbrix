"use client";

import { useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { cn } from "@qbrix/ui/lib/utils";
import { vizSeries } from "@qbrix/ui/components/belief-viz";
import {
  MAX_CONTEXT_DIM,
  BASELINE_WIDTH,
  propertyWidth,
  schemaWidth,
  type ContextProperty,
  type ContextSchema,
} from "@/lib/api/types";

// board `APP · New experiment / Context` and `APP · Context builder / States`.
// the width readout is the teaching surface: it carries the cost model, the cap
// and the failure. nothing else in the flow explains why a schema can be wide.

const TYPES: ContextProperty["type"][] = ["categorical", "numeric", "boolean"];

export type SchemaIssue = { index: number; message: string };

// validation exists for immediate feedback, not as a second implementation —
// the server owns the schema and rejects anything that gets past this.
export function validateSchema(schema: ContextSchema): SchemaIssue[] {
  const issues: SchemaIssue[] = [];
  const seen = new Map<string, number>();

  schema.forEach((p, i) => {
    const name = p.name.trim();
    if (!name) {
      issues.push({ index: i, message: "Needs a name" });
    } else if (seen.has(name)) {
      issues.push({ index: i, message: `“${name}” is declared twice` });
    } else {
      seen.set(name, i);
    }

    if (p.type === "categorical" && p.values.length === 0) {
      issues.push({ index: i, message: "Needs at least one value" });
    }
    if (p.type === "numeric" && !(p.min < p.max)) {
      issues.push({ index: i, message: "Min must be below max" });
    }
  });

  return issues;
}

export function schemaReady(schema: ContextSchema): boolean {
  return (
    schema.length > 0 &&
    validateSchema(schema).length === 0 &&
    schemaWidth(schema) <= MAX_CONTEXT_DIM
  );
}

function emptyOf(type: ContextProperty["type"], name: string): ContextProperty {
  if (type === "categorical") return { type, name, values: [] };
  if (type === "numeric") return { type, name, min: 0, max: 1 };
  return { type, name };
}

function ChipValues({
  values,
  onChange,
}: {
  values: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  // chips rather than a comma-separated field: free text invites trailing
  // spaces and duplicates the server would reject, turning a formatting slip
  // into a failed create.
  function commit(raw: string) {
    const next = raw
      .split(",")
      .map((v) => v.trim())
      .filter((v) => v && !values.includes(v));
    if (next.length) onChange([...values, ...next]);
    setDraft("");
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.map((v) => (
        <span
          key={v}
          className="group flex items-center gap-1 rounded bg-bg-panel px-1.5 py-0.5 text-[11px] text-text-secondary"
        >
          {v}
          <button
            type="button"
            onClick={() => onChange(values.filter((x) => x !== v))}
            className="text-text-dim transition-colors hover:text-text-secondary"
          >
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => {
          if (e.target.value.includes(",")) commit(e.target.value);
          else setDraft(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(draft);
          } else if (e.key === "Backspace" && !draft && values.length) {
            onChange(values.slice(0, -1));
          }
        }}
        onBlur={() => draft && commit(draft)}
        placeholder={values.length ? "" : "mobile, desktop"}
        className="min-w-[70px] flex-1 bg-transparent text-[11px] text-text-primary placeholder:text-text-dim outline-none"
      />
      {/* real, and it costs a slot — hiding it makes the width arithmetic look
          wrong. never editable: the user does not author it. */}
      <span className="rounded bg-bg-panel/60 px-1.5 py-0.5 text-[11px] text-text-faint">
        + other
      </span>
    </div>
  );
}

export function ContextSchemaBuilder({
  schema,
  onChange,
}: {
  schema: ContextSchema;
  onChange: (next: ContextSchema) => void;
}) {
  const width = schemaWidth(schema);
  const issues = useMemo(() => validateSchema(schema), [schema]);
  const overCap = width > MAX_CONTEXT_DIM;

  function update(index: number, next: ContextProperty) {
    onChange(schema.map((p, i) => (i === index ? next : p)));
  }

  function retype(index: number, type: ContextProperty["type"]) {
    update(index, emptyOf(type, schema[index].name));
  }

  const issueFor = (i: number) => issues.find((x) => x.index === i)?.message;

  // the widest property is the actionable one when the answer is "too wide"
  const widest = schema.reduce<{ name: string; w: number } | null>((acc, p) => {
    const w = propertyWidth(p);
    return !acc || w > acc.w ? { name: p.name.trim() || "a property", w } : acc;
  }, null);

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col divide-y divide-border rounded-lg border border-border">
        {schema.length === 0 ? (
          <div className="flex flex-col gap-1 px-3 py-4 text-center">
            <span className="text-[12px] text-text-secondary">No properties yet</span>
            <span className="text-[11px] leading-relaxed text-text-dim">
              Name what you already know about the request — device, country, plan.
              Fixed once the experiment is created.
            </span>
          </div>
        ) : (
          schema.map((p, i) => {
            const issue = issueFor(i);
            return (
              <div key={i} className="flex flex-col gap-1 px-3 py-2">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={p.name}
                    onChange={(e) => update(i, { ...p, name: e.target.value })}
                    placeholder="property"
                    className={cn(
                      "w-[104px] shrink-0 bg-transparent font-mono text-xs text-text-secondary placeholder:text-text-dim outline-none",
                      issue && "text-danger",
                    )}
                  />
                  <select
                    value={p.type}
                    onChange={(e) =>
                      retype(i, e.target.value as ContextProperty["type"])
                    }
                    className="shrink-0 appearance-none rounded border-none bg-bg-panel px-1.5 py-0.5 text-[11px] text-text-dim outline-none"
                  >
                    {TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>

                  <div className="min-w-0 flex-1">
                    {p.type === "categorical" && (
                      <ChipValues
                        values={p.values}
                        onChange={(values) => update(i, { ...p, values })}
                      />
                    )}
                    {p.type === "numeric" && (
                      <div className="flex items-center gap-1.5">
                        {(["min", "max"] as const).map((k) => (
                          <input
                            key={k}
                            type="number"
                            value={p[k]}
                            onChange={(e) =>
                              update(i, { ...p, [k]: Number(e.target.value) })
                            }
                            className="w-16 rounded bg-bg-panel px-1.5 py-0.5 text-[11px] text-text-primary outline-none"
                          />
                        ))}
                        <span className="text-[11px] text-text-faint">
                          clamped to range
                        </span>
                      </div>
                    )}
                    {p.type === "boolean" && (
                      <span className="text-[11px] text-text-faint">true / false</span>
                    )}
                  </div>

                  <span className="w-5 shrink-0 text-right font-mono text-[11px] text-text-dim">
                    {propertyWidth(p)}
                  </span>
                  <button
                    type="button"
                    onClick={() => onChange(schema.filter((_, x) => x !== i))}
                    className="shrink-0 text-text-dim transition-colors hover:text-text-secondary"
                  >
                    <X size={13} />
                  </button>
                </div>
                {issue && <span className="text-[11px] text-danger">{issue}</span>}
              </div>
            );
          })
        )}

        <button
          type="button"
          onClick={() => onChange([...schema, emptyOf("categorical", "")])}
          className="flex items-center justify-center gap-1.5 py-2 text-[13px] text-text-dim transition-colors hover:text-text-secondary"
        >
          <Plus size={13} />
          Add property
        </button>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-bg-panel px-3 py-2.5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[12px] text-text-secondary">Context width</span>
            <span
              className={cn(
                "font-mono text-[13px] font-bold",
                overCap ? "text-danger" : "text-text-primary",
              )}
            >
              {width}
            </span>
            <span className="font-mono text-[11px] text-text-faint">
              / {MAX_CONTEXT_DIM}
            </span>
          </div>
          <span className="text-[11px] text-text-faint">derived · not editable</span>
        </div>

        {/* the number answers "am I near the cap"; the bar answers "which
            property is eating it", the only actionable form when the answer
            is no. */}
        <div className="flex h-1.5 gap-px overflow-hidden rounded-full bg-bg">
          <div
            className="bg-text-faint"
            style={{ width: `${(BASELINE_WIDTH / MAX_CONTEXT_DIM) * 100}%` }}
          />
          {schema.map((p, i) => (
            <div
              key={i}
              className={vizSeries(i)}
              style={{
                width: `${Math.min(propertyWidth(p) / MAX_CONTEXT_DIM, 1) * 100}%`,
              }}
            />
          ))}
        </div>

        {overCap ? (
          <span className="text-[11px] leading-relaxed text-danger">
            Width {width} exceeds the {MAX_CONTEXT_DIM} limit
            {widest ? `, and ${widest.name} carries ${widest.w} of it` : ""}. Wider
            contexts cost selection latency on every request — each strategy inverts
            a width × width matrix per variant.
          </span>
        ) : schema.length === 0 ? (
          <span className="text-[11px] leading-relaxed text-text-faint">
            Width {BASELINE_WIDTH} is the reserved baseline slot. Contextual
            strategies need at least one property of your own.
          </span>
        ) : widest && widest.w >= 12 ? (
          <span className="text-[11px] leading-relaxed text-text-faint">
            {widest.name} carries {widest.w} slots. Bucketing it — continent, or your
            top five markets plus other — buys most of the signal for a tenth of the
            width.
          </span>
        ) : null}
      </div>
    </div>
  );
}
