"use client";

import { cn } from "@qbrix/ui/lib/utils";
import type { PolicyParam } from "@/lib/api/types";

// `/v1/policies` emits pydantic's constraint vocabulary — gt / gte / lt / lte.
// it never emits min/max, which is what this form used to read, so no bound was
// ever enforced and out-of-range values were only caught by the API's 400.

export type Bounds = {
  min?: number;
  max?: number;
  minExclusive: boolean;
  maxExclusive: boolean;
};

export function bounds(param: PolicyParam): Bounds {
  const c = param.constraints ?? {};
  const min = "gt" in c ? c.gt : "gte" in c ? c.gte : undefined;
  const max = "lt" in c ? c.lt : "lte" in c ? c.lte : undefined;
  return {
    min,
    max,
    minExclusive: "gt" in c,
    maxExclusive: "lt" in c,
  };
}

// interval notation: (0, ∞) reads unambiguously and stays short enough to sit
// beside a 140px input, which "greater than 0 and at most 1" does not.
export function rangeHint(param: PolicyParam): string | null {
  const b = bounds(param);
  if (b.min === undefined && b.max === undefined) return null;
  const lo = b.min === undefined ? "(-∞" : `${b.minExclusive ? "(" : "["}${b.min}`;
  const hi = b.max === undefined ? "∞)" : `${b.max}${b.maxExclusive ? ")" : "]"}`;
  return `${lo}, ${hi}`;
}

/** the string the field shows before the user touches it */
export function initialValue(
  param: PolicyParam,
  current: Record<string, unknown>,
): string {
  const v = current[param.name];
  if (v !== undefined && v !== null) return String(v);
  if (param.default !== null && param.default !== undefined) {
    return String(param.default);
  }
  return "";
}

export function validate(param: PolicyParam, raw: string): string | null {
  const s = raw.trim();
  if (s === "") {
    // absent is fine for an optional param — the server applies the default
    return param.required ? "Required" : null;
  }

  const v = Number(s);
  if (!Number.isFinite(v)) return "Must be a number";
  if (param.type === "integer" && !Number.isInteger(v)) {
    return "Must be a whole number";
  }

  const b = bounds(param);
  if (b.min !== undefined) {
    if (b.minExclusive ? v <= b.min : v < b.min) {
      return `Must be ${b.minExclusive ? "greater than" : "at least"} ${b.min}`;
    }
  }
  if (b.max !== undefined) {
    if (b.maxExclusive ? v >= b.max : v > b.max) {
      return `Must be ${b.maxExclusive ? "less than" : "at most"} ${b.max}`;
    }
  }
  return null;
}

// board `APP · Experiment / Policy` / Fields: hairline-separated rows, a 300px
// label column and the control on the right.
//
// every param the API exposes is numeric, and each is either half-bounded
// (`{gt: 0}` — a slider has no second end to anchor) or a precision value like
// gamma = 0.999, where a 0–1 slider cannot express the value at all. so the
// board's slider row is not built; a number input carries all of them.
export function ParamField({
  param,
  value,
  error,
  onChange,
}: {
  param: PolicyParam;
  value: string;
  error: string | null;
  onChange: (v: string) => void;
}) {
  const hint = rangeHint(param);

  return (
    <div className="flex gap-8 border-t border-border-subtle py-5">
      <div className="flex w-[300px] shrink-0 flex-col gap-1.5">
        <label
          htmlFor={`param-${param.name}`}
          className="font-mono text-[15px] font-medium tracking-[0.2px] text-text-primary"
        >
          {param.name}
        </label>
        {param.description && (
          <p className="text-[13.5px] leading-[1.5] text-text-faint">
            {param.description}
          </p>
        )}
      </div>

      {/* top-aligned, not centred: a long description makes a tall row and the
          board keeps the control level with the label's first line */}
      <div className="flex flex-1 items-start gap-3">
        <input
          id={`param-${param.name}`}
          type="text"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={param.required ? "required" : ""}
          aria-invalid={!!error}
          className={cn(
            "h-10 w-[140px] shrink-0 rounded-[10px] border bg-bg-panel px-3.5 font-mono text-[14.5px] tracking-[0.3px] text-text-primary outline-none transition-colors placeholder:text-text-faint",
            error
              ? "border-danger/60"
              : "border-border focus:border-border-strong",
          )}
        />
        {error ? (
          <span className="pt-[11px] text-[13px] text-danger">{error}</span>
        ) : (
          hint && (
            <span className="pt-[11px] font-mono text-[13px] text-text-faint">
              {hint}
            </span>
          )
        )}
      </div>
    </div>
  );
}
