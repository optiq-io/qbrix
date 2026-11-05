"use client";

import { useRef } from "react";
import { cn } from "../lib/utils";

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  boxed,
  className,
}: {
  /** the group's accessible name: "Range" */
  label: string;
  value: T;
  /** an option with an icon shows only the icon, and its label names it */
  options: { value: T; label: string; count?: number; icon?: React.ReactNode }[];
  onChange: (value: T) => void;
  /** the page's main filter: a larger control in its own outline */
  boxed?: boolean;
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
    <div ref={groupRef} role="radiogroup" aria-label={label} className={cn("inline-flex gap-0.5", boxed && "rounded-n-control border border-n-line p-px", className)}>
      {options.map((option, at) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={option.icon ? option.label : undefined}
            title={option.icon ? option.label : undefined}
            tabIndex={checked ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(e) => onKeyDown(e, at)}
            className={cn(
              "rounded-n-chip transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-n-ink",
              option.icon
                ? "flex h-[22px] w-[26px] items-center justify-center"
                : boxed
                  ? "n-meta px-2 py-[3px] font-medium leading-4"
                  : "n-label px-1.5 py-0.5 font-normal",
              checked ? "bg-n-fill-2 text-n-text-1" : boxed ? "text-n-text-2 hover:text-n-text-1" : "text-n-text-3 hover:text-n-text-1",
            )}
          >
            {option.icon ?? option.label}
            {option.count !== undefined && <span className={cn("ml-1.5 tabular-nums text-n-text-3", boxed && "n-label font-normal")}>{option.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
