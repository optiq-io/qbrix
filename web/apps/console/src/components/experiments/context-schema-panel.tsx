"use client";

import {
  MAX_CONTEXT_DIM,
  BASELINE_WIDTH,
  propertyWidth,
  schemaWidth,
  type ContextProperty,
  type ContextSchema,
} from "@/lib/api/types";

// board `APP · Experiment / Policy · Context schema`. the read-only counterpart
// to the builder: what every select must send, and how wide the vector it
// becomes. no controls — the schema is fixed at creation.

// policy_params is Record<string, unknown>, so the stored schema is unverified
// at the type level. shape-check it rather than trusting the cast: an older
// experiment predating the schema, or a hand-written policy_params, would
// otherwise render as blanks.
export function readContextSchema(params: Record<string, unknown>): ContextSchema | null {
  const raw = params.context_schema;
  if (!Array.isArray(raw) || raw.length === 0) return null;

  const out: ContextProperty[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") return null;
    const p = item as Record<string, unknown>;
    if (typeof p.name !== "string") return null;
    if (p.type === "categorical" && Array.isArray(p.values)) {
      out.push({ type: "categorical", name: p.name, values: p.values.map(String) });
    } else if (p.type === "numeric" && typeof p.min === "number" && typeof p.max === "number") {
      out.push({ type: "numeric", name: p.name, min: p.min, max: p.max });
    } else if (p.type === "boolean") {
      out.push({ type: "boolean", name: p.name });
    } else {
      return null;
    }
  }
  return out;
}

function valuesOf(p: ContextProperty): string {
  if (p.type === "categorical") return [...p.values, "+ other"].join(", ");
  if (p.type === "numeric") return `${p.min} — ${p.max}`;
  return "true / false";
}

function Cell({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={className}>{children}</div>;
}

export function ContextSchemaPanel({ schema }: { schema: ContextSchema }) {
  const width = schemaWidth(schema);

  return (
    <div className="mt-[30px]">
      <h2 className="text-[17px] font-semibold tracking-[-0.3px] text-text-primary">
        Context schema
      </h2>

      <p className="mt-2 max-w-[620px] text-[13.5px] leading-[1.5] text-text-dim">
        Every select must send these properties. qbrix encodes them into the feature
        vector — you never build one. Both the properties and the width they derive are
        fixed for the life of the experiment.
      </p>

      <div className="mt-[22px] flex flex-col">
        <div className="flex items-center gap-3 border-b border-border-subtle py-[9px] font-mono text-[10px] tracking-[0.6px] text-text-faint">
          <Cell className="w-[132px] shrink-0">PROPERTY</Cell>
          <Cell className="w-[108px] shrink-0">TYPE</Cell>
          <Cell className="flex-1">VALUES</Cell>
          <Cell className="w-[52px] shrink-0 text-right">WIDTH</Cell>
        </div>

        {schema.map((p) => (
          <div
            key={p.name}
            className="flex items-center gap-3 border-b border-border-subtle py-[11px]"
          >
            <Cell className="w-[132px] shrink-0 text-[14px] text-text-secondary">
              {p.name}
            </Cell>
            <Cell className="w-[108px] shrink-0 text-[13.5px] text-text-dim">{p.type}</Cell>
            <Cell className="flex-1 text-[13.5px] text-text-dim">{valuesOf(p)}</Cell>
            <Cell className="w-[52px] shrink-0 text-right font-mono text-[14px] text-text-secondary">
              {propertyWidth(p)}
            </Cell>
          </div>
        ))}

        {/* counted, muted, never a row you could act on — the properties sum to
            one number and the width reads one higher, so hiding it would leave
            the arithmetic unverifiable. */}
        <div className="flex items-center gap-3 border-b border-border-subtle py-[11px] text-text-faint">
          <Cell className="w-[132px] shrink-0 text-[14px]">baseline</Cell>
          <Cell className="w-[108px] shrink-0 text-[13.5px]">reserved</Cell>
          <Cell className="flex-1 text-[13.5px]">one slot every schema carries</Cell>
          <Cell className="w-[52px] shrink-0 text-right font-mono text-[14px]">
            {BASELINE_WIDTH}
          </Cell>
        </div>

        <div className="flex items-center justify-between gap-3 py-[13px]">
          <span className="text-[14px] text-text-secondary">Context width</span>
          <span className="flex items-baseline gap-1.5">
            <span className="font-mono text-[14px] font-semibold text-text-primary">
              {width}
            </span>
            <span className="font-mono text-[12px] text-text-faint">
              / {MAX_CONTEXT_DIM}
            </span>
          </span>
        </div>
      </div>

      <p className="mt-1.5 max-w-[620px] text-[12px] leading-[1.5] text-text-faint">
        The schema cannot be changed after creation, like a pool&apos;s arms and an
        experiment&apos;s strategy — the learned parameters have its width baked in, so
        widening it would invalidate everything trained so far. To change the shape,
        create a new experiment.
      </p>
    </div>
  );
}
