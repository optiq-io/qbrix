"use client";

import { useId } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";
import { cn } from "../lib/utils";
import { CONTROL } from "./field";
import { PANEL } from "./overlay";
import { usePopover } from "./popover";

export type PickerOption<T extends string> = { value: T; label: string; hint?: string };

const ROW =
  "flex w-full items-center gap-2 rounded-n-chip px-2.5 py-1.5 text-left outline-none hover:bg-n-fill-1 focus:bg-n-fill-1";

export function Picker<T extends string>({
  label,
  value,
  options,
  onChange,
  placeholder = "Choose…",
  create,
  hint,
  canEdit = true,
  className,
}: {
  label: string;
  value: T | null;
  options: PickerOption<T>[];
  onChange: (value: T) => void;
  placeholder?: string;
  /** the last row, for when what they want doesn't exist yet: "Create metric" */
  create?: { label: string; onSelect: () => void };
  hint?: string;
  /** false for a person who can't make this change: the picker is absent, never disabled */
  canEdit?: boolean;
  className?: string;
}) {
  const { open, setOpen, close, wrapperRef, triggerRef, contentRef, onContentKeyDown, onTriggerKeyDown } =
    usePopover("option");
  const id = useId();
  if (!canEdit) return null;

  const selected = options.find((o) => o.value === value);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <span id={`${id}-label`} className="n-meta font-medium text-n-text-3">
        {label}
      </span>
      <div ref={wrapperRef} className="relative">
        <button
          ref={triggerRef}
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-labelledby={`${id}-label ${id}-value`}
          onClick={() => setOpen((v) => !v)}
          onKeyDown={onTriggerKeyDown}
          className={cn(CONTROL, "n-body flex items-center justify-between gap-2 text-left")}
        >
          <span id={`${id}-value`} className={selected ? "text-n-text-1" : "text-n-text-3"}>
            {selected?.label ?? placeholder}
          </span>
          <ChevronDown size={14} className="shrink-0 text-n-text-3" />
        </button>

        {open && (
          <div
            ref={contentRef}
            role="listbox"
            aria-labelledby={`${id}-label`}
            onKeyDown={onContentKeyDown}
            className={cn(
              PANEL,
              "absolute inset-x-0 top-[calc(100%+4px)] z-30 flex max-h-72 flex-col overflow-y-auto p-1 shadow-[0_8px_24px_#0000001f]",
            )}
          >
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                tabIndex={-1}
                onClick={() => {
                  close();
                  onChange(option.value);
                }}
                className={ROW}
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="n-body text-n-text-1">{option.label}</span>
                  {option.hint && <span className="n-meta text-n-text-3">{option.hint}</span>}
                </span>
                {option.value === value && <Check size={14} className="shrink-0 text-n-text-1" />}
              </button>
            ))}
            {create && (
              <button
                type="button"
                role="option"
                aria-selected={false}
                tabIndex={-1}
                onClick={() => {
                  close();
                  create.onSelect();
                }}
                className={cn(ROW, "n-body text-n-text-2", options.length > 0 && "mt-1 border-t border-n-line-2 rounded-t-none pt-2")}
              >
                <Plus size={14} className="shrink-0" />
                {create.label}
              </button>
            )}
          </div>
        )}
      </div>
      {hint && <p className="n-label font-normal text-n-text-3">{hint}</p>}
    </div>
  );
}
