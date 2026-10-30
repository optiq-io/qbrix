"use client";

import { useRef } from "react";
import { cn } from "../lib/utils";

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: {
  /** the group's accessible name: "Range" */
  label: string;
  value: T;
  options: { value: T; label: string; count?: number }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  const groupRef = useRef<HTMLDivElement>(null);

  const onKeyDown = (e: React.KeyboardEvent, at: number) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (at + step + options.length) % options.length;
    onChange(options[next].value);
    groupRef.current?.querySelectorAll<HTMLElement>('[role="radio"]')[next]?.focus();
  };

  return (
    <div ref={groupRef} role="radiogroup" aria-label={label} className={cn("inline-flex gap-0.5", className)}>
      {options.map((option, at) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(e) => onKeyDown(e, at)}
            className={cn(
              "n-label rounded-n-chip px-1.5 py-0.5 font-normal transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-n-ink",
              checked ? "bg-n-fill-2 text-n-text-1" : "text-n-text-3 hover:text-n-text-1",
            )}
          >
            {option.label}
            {option.count !== undefined && <span className="ml-1.5 tabular-nums text-n-text-3">{option.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
